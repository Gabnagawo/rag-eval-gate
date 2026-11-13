from __future__ import annotations

import io
import shutil
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from rag_eval_gate.cli import app, echo
from rag_eval_gate.config import RagConfig, Threshold, load_eval_config, load_rag_config
from rag_eval_gate.evaluate import (
    Evaluator,
    Results,
    RunInfo,
    load_results,
    restrict,
    summarize,
)
from rag_eval_gate.gate import evaluate_gate, render_markdown
from rag_eval_gate.golden import GoldenItem
from rag_eval_gate.llm import FakeGenerator, HashEmbedder
from rag_eval_gate.metrics import Sample, hit_rate, mrr
from rag_eval_gate.rag import RagPipeline, VectorIndex
from tests.conftest import ROOT

runner = CliRunner()

ITEMS = [
    GoldenItem(
        id="downloads",
        question="What happens to downloaded files when the browser context is closed?",
        reference="They are deleted when the context closes.",
        sources=["downloads"],
        evidence="deleted",
    ),
    GoldenItem(
        id="screenshot",
        question="How do I take a full page screenshot of the scrollable page?",
        reference="page.screenshot(full_page=True)",
        sources=["screenshots"],
        evidence="full_page",
    ),
]


def run_info(cfg: RagConfig, metrics: list[str]) -> RunInfo:
    return RunInfo(
        run_id="t",
        profile="local",
        started_at=datetime.now(UTC),
        generator="fake/fake",
        judge_model="judge",
        embed_model="hash-bow",
        rag_config=cfg.model_dump(mode="json"),
        corpus_sha256="x",
        golden_sha256="y",
        metrics=metrics,
    )


def pipeline(cfg: RagConfig) -> RagPipeline:
    emb = HashEmbedder()
    return RagPipeline(VectorIndex.build(cfg, emb, cache_dir=None), emb, FakeGenerator(), cfg)


def test_evaluator_scores_records_errors_and_resumes(rag_cfg: RagConfig, tmp_path: Path) -> None:
    calls: list[str] = []

    def answer_len(s: Sample) -> float:
        calls.append(s.id)
        return min(1.0, len(s.answer) / 100)

    def broken(s: Sample) -> float:
        raise RuntimeError("judge timed out")

    fns = {"hit_rate": hit_rate, "answer_len": answer_len, "broken": broken}
    out = tmp_path / "r.json"
    seen: list[str] = []
    ev = Evaluator(
        pipeline(rag_cfg),
        fns,
        out,
        run_info(rag_cfg, list(fns)),
        lambda i, n, r: seen.append(r["id"]),
    )
    results = ev.run(ITEMS)
    assert seen == ["downloads", "screenshot"]
    first = results.samples[0]
    assert first["metrics"]["hit_rate"] == 1.0
    assert first["metrics"]["broken"] is None
    assert first["errors"]["broken"] == "RuntimeError: judge timed out"
    assert first["answer"]
    assert first["retrieved"][0]["source"] == "downloads"
    assert set(first["timings_s"]) >= {"retrieval", "generation", "hit_rate"}
    assert results.summary["broken"].failed == 2
    assert results.summary["hit_rate"].mean == 1.0
    assert load_results(out).run.finished_at is not None

    # Resume: a sample is redone when a requested metric is missing or failed.
    calls.clear()
    Evaluator(pipeline(rag_cfg), fns, out, run_info(rag_cfg, list(fns))).run(ITEMS, resume=True)
    assert calls == ["downloads", "screenshot"]  # "broken" failed, so both are redone
    ok_fns = {"hit_rate": hit_rate, "answer_len": answer_len}
    calls.clear()
    Evaluator(pipeline(rag_cfg), ok_fns, out, run_info(rag_cfg, list(ok_fns))).run(
        ITEMS, resume=True
    )
    assert calls == []  # every requested metric is already scored
    # A different rag config never reuses old samples.
    other = rag_cfg.model_copy(update={"top_k": 1})
    Evaluator(pipeline(other), ok_fns, out, run_info(other, list(ok_fns))).run(ITEMS, resume=True)
    assert calls == ["downloads", "screenshot"]


def test_retrieval_only_runs_skip_generation(rag_cfg: RagConfig, tmp_path: Path) -> None:
    fns = {"hit_rate": hit_rate, "mrr": mrr}
    ev = Evaluator(pipeline(rag_cfg), fns, tmp_path / "r.json", run_info(rag_cfg, list(fns)))
    assert all(s["answer"] == "" for s in ev.run(ITEMS).samples)


def results_with(means: dict[str, float | None], failed: int = 0) -> Results:
    samples = [{"id": "a", "metrics": dict(means)}]
    res = Results(run=run_info(RagConfig(), list(means)), samples=samples)
    res.summary = summarize(samples, list(means))
    if failed:
        for s in res.summary.values():
            s.failed = failed
    return res


def test_restrict_recomputes_summary() -> None:
    res = results_with({"faithfulness": 0.5})
    res.samples.append({"id": "b", "metrics": {"faithfulness": 1.0}})
    res.summary = summarize(res.samples, ["faithfulness"])
    assert res.summary["faithfulness"].mean == 0.75
    only_b = restrict(res, {"b"})
    assert only_b.summary["faithfulness"].mean == 1.0
    assert [s["id"] for s in only_b.samples] == ["b"]


def test_gate_pass_fail_and_reasons() -> None:
    thresholds = {
        "faithfulness": Threshold(min=0.7),
        "hallucination": Threshold(max=0.5),
        "context_recall": Threshold(min=0.6, max=1.0),
        "missing": Threshold(min=0.1),
    }
    res = results_with({"faithfulness": 0.8, "hallucination": 0.6, "context_recall": 0.5})
    verdict = evaluate_gate(res, thresholds)
    status = {c.metric: (c.passed, c.reason) for c in verdict.checks}
    assert status == {
        "faithfulness": (True, "ok"),
        "hallucination": (False, "above 0.50"),
        "context_recall": (False, "below 0.60"),
        "missing": (False, "not measured"),
    }
    assert not verdict.passed
    bounds = {c.metric: c.bound for c in verdict.checks}
    assert bounds == {
        "faithfulness": ">= 0.70",
        "hallucination": "<= 0.50",
        "context_recall": "0.60 to 1.00",
        "missing": ">= 0.10",
    }


def test_gate_fails_when_too_many_judge_calls_failed() -> None:
    res = results_with({"faithfulness": 0.9}, failed=3)
    verdict = evaluate_gate(res, {"faithfulness": Threshold(min=0.5)})
    assert verdict.checks[0].reason == "3/4 judge calls failed"
    with pytest.raises(ValueError, match="min or max"):
        Threshold()


def test_markdown_with_and_without_baseline() -> None:
    head = results_with({"faithfulness": 0.6})
    base = results_with({"faithfulness": 0.9})
    thresholds = {"faithfulness": Threshold(min=0.7)}
    plain = render_markdown(evaluate_gate(head, thresholds), head)
    assert "❌ RAG eval gate failed" in plain
    assert "| faithfulness | 0.600 | >= 0.70 | **FAIL** (below 0.70) |" in plain
    compared = render_markdown(evaluate_gate(head, thresholds, base), head, base)
    assert "| faithfulness | 0.900 | 0.600 | -0.300 | >= 0.70 |" in compared
    ok = results_with({"faithfulness": 0.95})
    assert "✅ RAG eval gate passed" in render_markdown(evaluate_gate(ok, thresholds), ok)


def test_evaluator_unloads_every_n_scored_questions(rag_cfg: RagConfig, tmp_path: Path) -> None:
    events: list[str] = []

    def metric(s: Sample) -> float:
        events.append(s.id)
        return 1.0

    fns = {"m": metric}
    items = [ITEMS[i % len(ITEMS)].model_copy(update={"id": f"q{i}"}) for i in range(5)]

    def unload() -> None:
        events.append("unload")

    def run(out: str, unload_every: int | None, callback: Callable[[], None] | None) -> None:
        events.clear()
        info = run_info(rag_cfg, ["m"])
        Evaluator(
            pipeline(rag_cfg), fns, tmp_path / out, info, unload_every=unload_every, unload=callback
        ).run(items, resume=True)

    run("a.json", 2, unload)
    # between questions only: never before the first one, never after the last one
    assert events == ["q0", "q1", "unload", "q2", "q3", "unload", "q4"]
    run("a.json", 2, unload)
    assert events == []  # everything already scored: nothing to unload for
    run("b.json", None, unload)
    assert "unload" not in events  # off by default
    run("c.json", 1, None)
    assert events == ["q0", "q1", "q2", "q3", "q4"]  # no callback: nothing to call


def test_echo_survives_a_console_that_cannot_encode_the_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = io.BytesIO()
    monkeypatch.setattr("sys.stdout", io.TextIOWrapper(raw, encoding="cp1252", newline="\n"))
    echo("\u2705 RAG eval gate passed")
    assert raw.getvalue() == b"? RAG eval gate passed\n"


def test_cli_passes_the_profile_unload_setting(project: Path) -> None:
    # Offline runs never call Ollama, so the option is accepted and ignored.
    out = runner.invoke(
        app, ["eval", "--offline", "--unload-every", "1", "--out", "results/u.json"]
    )
    assert out.exit_code == 0, out.output
    assert "0 runner reloads" in out.output


def test_committed_configs_load() -> None:
    # rag.yaml is what a retrieval PR edits, so only its validity is asserted here.
    cfg = load_rag_config(ROOT / "rag.yaml")
    assert cfg.top_k >= 1
    assert cfg.chunk_overlap < cfg.chunk_size
    ecfg = load_eval_config(ROOT / "eval.yaml")
    assert "faithfulness" in ecfg.profile("local").thresholds
    # `make demo` and the PR workflow run the ci profile: a subset, gated on every metric.
    ci = ecfg.profile("ci")
    assert ci.limit == 8
    assert set(ci.thresholds) == set(ecfg.metrics)
    assert ecfg.profile("local").limit is None
    assert ci.unload_every is None  # off unless a profile asks for it
    assert ecfg.profile("local").unload_every == 3
    with pytest.raises(KeyError, match="unknown profile"):
        ecfg.profile("nope")
    with pytest.raises(ValueError, match="chunk_overlap"):
        RagConfig(chunk_size=200, chunk_overlap=200)


@pytest.fixture
def project(tmp_path: Path, corpus_dir: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A miniature project directory: corpus, rag.yaml, eval.yaml and a golden set."""
    shutil.copytree(corpus_dir, tmp_path / "data" / "corpus")
    (tmp_path / "rag.yaml").write_text(
        "corpus_dir: data/corpus\nchunk_size: 200\nchunk_overlap: 20\ntop_k: 2\n", encoding="utf-8"
    )
    (tmp_path / "eval").mkdir()
    golden = {"items": [i.model_dump() for i in ITEMS]}
    (tmp_path / "eval" / "golden.yaml").write_text(yaml.safe_dump(golden), encoding="utf-8")
    (tmp_path / "eval.yaml").write_text(
        "golden_set: eval/golden.yaml\n"
        "profiles:\n"
        "  local:\n"
        "    thresholds: {hit_rate: {min: 0.9}, mrr: {min: 0.9}}\n"
        "  strict:\n"
        "    thresholds: {hit_rate: {min: 0.5}, faithfulness: {min: 0.5}}\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_cli_offline_index_ask_eval_and_gate(project: Path) -> None:
    out = runner.invoke(app, ["index", "--offline"])
    assert out.exit_code == 0, out.output
    assert "chunks from 2 pages" in out.output
    ask = runner.invoke(app, ["ask", "What happens to downloaded files?", "--offline"])
    assert ask.exit_code == 0
    assert "[1] downloads#" in ask.output
    ev = runner.invoke(app, ["eval", "--offline", "--out", "results/r.json"])
    assert ev.exit_code == 0, ev.output
    assert "2 questions, profile local, generator fake/fake, judge None" in ev.output
    assert "hit_rate           1.000  (n=2)" in ev.output
    gate = runner.invoke(app, ["gate", "results/r.json", "--comment", "c/comment.md"])
    assert gate.exit_code == 0
    assert "passed" in (project / "c" / "comment.md").read_text(encoding="utf-8")
    strict = runner.invoke(
        app, ["gate", "results/r.json", "--profile", "strict", "--baseline", "results/r.json"]
    )
    assert strict.exit_code == 1
    assert "| hit_rate | 1.000 | 1.000 | +0.000 | >= 0.50 | pass |" in strict.output
    assert "| faithfulness | n/a | n/a | n/a | >= 0.50 | **FAIL** (not measured) |" in strict.output


def test_cli_eval_options(project: Path) -> None:
    only = runner.invoke(
        app, ["eval", "--offline", "--only", "screenshot", "--out", "results/o.json"]
    )
    assert "1 questions" in only.output
    limited = runner.invoke(app, ["eval", "--offline", "--limit", "1", "--out", "results/l.json"])
    assert "1 questions" in limited.output
    bad = runner.invoke(app, ["eval", "--metrics", "bleu", "--out", "results/b.json"])
    assert bad.exit_code != 0
    assert runner.invoke(app, ["--version"]).output.strip() == "rag-eval-gate 0.1.0"


def test_cli_corpus_build(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    for name in ("a",):
        (raw / f"{name}.md").write_text("---\ntitle: A\n---\n\nText.\n", encoding="utf-8")
    from rag_eval_gate import cli

    written = cli.build_corpus(raw, tmp_path / "out", pages=["a"])
    assert written[0].read_text(encoding="utf-8") == "# A\n\nText.\n"
    result = runner.invoke(app, ["corpus", "build", str(raw), "--out-dir", str(tmp_path / "o2")])
    assert result.exit_code != 0  # the default page list is not in this raw dir
