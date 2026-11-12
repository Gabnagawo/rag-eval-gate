"""``rag-gate``: build the index, ask questions, evaluate the golden set and enforce the gate."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

import typer

from rag_eval_gate import __version__
from rag_eval_gate.config import Settings, load_eval_config, load_rag_config
from rag_eval_gate.corpus import DEFAULT_PAGES, build_corpus, corpus_sha256, load_corpus
from rag_eval_gate.evaluate import Evaluator, RunInfo, load_results, restrict, versions
from rag_eval_gate.gate import evaluate_gate, render_markdown
from rag_eval_gate.golden import golden_sha256, load_golden
from rag_eval_gate.llm import (
    Embedder,
    Generator,
    HashEmbedder,
    OllamaEmbedder,
    build_client,
    build_generator,
)
from rag_eval_gate.metrics import RETRIEVAL_METRICS, LLMJudge, metric_functions
from rag_eval_gate.rag import RagPipeline, VectorIndex

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="A RAG pipeline over the Playwright Python docs with a RAGAS + DeepEval quality gate.",
)
corpus_app = typer.Typer(no_args_is_help=True, help="Build the corpus snapshot.")
app.add_typer(corpus_app, name="corpus")

RagOpt = Annotated[Path, typer.Option("--rag-config", help="Pipeline under test.")]
EvalOpt = Annotated[Path, typer.Option("--eval-config", help="Golden set, thresholds, profiles.")]


def echo(text: str = "") -> None:
    sys.stdout.write(text + "\n")
    sys.stdout.flush()


def _version(value: bool) -> None:
    if value:
        echo(f"rag-eval-gate {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool, typer.Option("--version", callback=_version, is_eager=True, help="Show version.")
    ] = False,
) -> None:
    """A RAG pipeline over the Playwright Python docs with a RAGAS + DeepEval quality gate."""


def _components(
    rag_config: Path, generator_fallback: str, offline: bool
) -> tuple[Settings, Any, Embedder, Generator, Any]:
    settings = Settings()
    cfg = load_rag_config(rag_config)
    client = build_client(settings)
    embedder: Embedder
    if offline:
        embedder = HashEmbedder()
        settings = settings.model_copy(update={"llm_provider": "fake"})
    else:
        embedder = OllamaEmbedder(client, settings.embed_model or cfg.embed_model)
    generator = build_generator(settings, client, generator_fallback)
    return settings, cfg, embedder, generator, client


@app.command()
def index(
    rag_config: RagOpt = Path("rag.yaml"),
    offline: Annotated[bool, typer.Option(help="Hash embeddings, no Ollama.")] = False,
) -> None:
    """Chunk and embed the corpus (cached under .cache/index)."""
    _, cfg, embedder, _, _ = _components(rag_config, "qwen3:8b", offline)
    idx = VectorIndex.build(cfg, embedder, progress=True)
    sizes = [len(c.text) for c in idx.chunks]
    echo(
        f"{len(idx.chunks)} chunks from {len({c.source for c in idx.chunks})} pages, "
        f"mean {sum(sizes) / len(sizes):.0f} chars, embeddings {embedder.model} "
        f"({idx.vectors.shape[1]} dims)"
    )


@app.command()
def ask(
    question: Annotated[str, typer.Argument()],
    rag_config: RagOpt = Path("rag.yaml"),
    model: Annotated[str, typer.Option(help="Generator model (Ollama).")] = "qwen3:8b",
    offline: Annotated[bool, typer.Option(help="Hash embeddings + fake generator.")] = False,
) -> None:
    """Answer one question from the corpus and show the retrieved passages."""
    _, cfg, embedder, generator, _ = _components(rag_config, model, offline)
    pipeline = RagPipeline(VectorIndex.build(cfg, embedder), embedder, generator, cfg)
    answer = pipeline.answer(question)
    echo(answer.answer)
    echo()
    for n, r in enumerate(answer.retrieved, start=1):
        echo(f"[{n}] {r.chunk.id}  {r.score:.3f}  {r.chunk.heading}")
    echo(f"(retrieval {answer.retrieval_s:.2f} s, generation {answer.generation_s:.1f} s)")


@app.command("eval")
def run_eval(
    profile: Annotated[str, typer.Option(help="Profile from eval.yaml.")] = "local",
    out: Annotated[Path, typer.Option(help="Results JSON.")] = Path("results/eval.json"),
    limit: Annotated[int | None, typer.Option(help="Override the profile's limit.")] = None,
    only: Annotated[list[str] | None, typer.Option(help="Golden ids to evaluate.")] = None,
    metrics: Annotated[
        str | None, typer.Option(help="Comma-separated subset of eval.yaml metrics.")
    ] = None,
    resume: Annotated[bool, typer.Option(help="Keep already scored samples in --out.")] = False,
    offline: Annotated[
        bool, typer.Option(help="Retrieval metrics only, hash embeddings, fake generator.")
    ] = False,
    rag_config: RagOpt = Path("rag.yaml"),
    eval_config: EvalOpt = Path("eval.yaml"),
) -> None:
    """Answer the golden questions and score them; writes the results JSON."""
    ecfg = load_eval_config(eval_config)
    prof = ecfg.profile(profile)
    settings, cfg, embedder, generator, client = _components(
        rag_config, prof.generator_model, offline
    )
    names = metrics.split(",") if metrics else list(ecfg.metrics)
    if offline:
        names = [n for n in names if n in RETRIEVAL_METRICS]
    judge_model = settings.judge_model or prof.judge_model
    judge = None if offline else LLMJudge(client, judge_model, embedder.model)
    try:
        fns = metric_functions(names, judge)
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="--metrics") from exc

    golden = load_golden(ecfg.golden_set)
    items = golden.items
    if only:
        items = [i for i in items if i.id in only]
    n = limit or prof.limit
    if n:
        items = items[:n]
    idx = VectorIndex.build(cfg, embedder, progress=True)
    run = RunInfo(
        run_id=out.stem,
        profile=profile,
        started_at=datetime.now(UTC),
        generator=f"{settings.llm_provider}/{generator.model}",
        judge_model=None if offline else judge_model,
        embed_model=embedder.model,
        rag_config=cfg.model_dump(mode="json"),
        corpus_sha256=corpus_sha256(load_corpus(cfg.corpus_dir)),
        golden_sha256=golden_sha256(ecfg.golden_set),
        metrics=names,
        versions=versions(),
    )
    echo(
        f"rag-eval-gate {__version__}: {len(items)} questions, profile {profile}, "
        f"generator {run.generator}, judge {run.judge_model}, top_k {cfg.top_k}, "
        f"chunk_size {cfg.chunk_size}, {len(idx.chunks)} chunks"
    )

    def progress(i: int, total: int, record: dict[str, Any]) -> None:
        scores = "  ".join(
            f"{k}={v:.2f}" if v is not None else f"{k}=ERR" for k, v in record["metrics"].items()
        )
        secs = sum(record["timings_s"].values())
        echo(f"[{i:>2}/{total}] {record['id']:<26} {scores}  ({secs:.0f} s)")

    evaluator = Evaluator(RagPipeline(idx, embedder, generator, cfg), fns, out, run, progress)
    results = evaluator.run(items, resume=resume)
    echo()
    for name, s in results.summary.items():
        mean = f"{s.mean:.3f}" if s.mean is not None else "n/a"
        failed = f", {s.failed} failed" if s.failed else ""
        echo(f"{name:<18} {mean}  (n={s.n}{failed})")
    echo(f"judge/LLM requests: {client.calls}; results: {out.as_posix()}")


@app.command()
def gate(
    results_path: Annotated[Path, typer.Argument(help="Results JSON from `rag-gate eval`.")],
    baseline: Annotated[
        Path | None, typer.Option(help="Results of the base branch, for the delta column.")
    ] = None,
    profile: Annotated[str | None, typer.Option(help="Defaults to the results' profile.")] = None,
    comment: Annotated[Path | None, typer.Option(help="Write the PR comment here.")] = None,
    eval_config: EvalOpt = Path("eval.yaml"),
) -> None:
    """Fail (exit 1) if any metric breaks its threshold in eval.yaml."""
    results = load_results(results_path)
    base = restrict(load_results(baseline), results.sample_ids()) if baseline else None
    prof = load_eval_config(eval_config).profile(profile or results.run.profile)
    verdict = evaluate_gate(results, prof.thresholds, base)
    text = render_markdown(verdict, results, base)
    if comment:
        comment.parent.mkdir(parents=True, exist_ok=True)
        comment.write_text(text, encoding="utf-8", newline="\n")
    echo(text)
    if not verdict.passed:
        raise typer.Exit(1)


@corpus_app.command("build")
def corpus_build(
    raw_dir: Annotated[Path, typer.Argument(help="Raw upstream docs/src pages.")],
    out_dir: Annotated[Path, typer.Option()] = Path("data/corpus"),
) -> None:
    """Clean raw Playwright doc pages into the Python-only corpus."""
    written = build_corpus(raw_dir, out_dir)
    echo(f"wrote {len(written)} pages to {out_dir.as_posix()}")


@corpus_app.command("fetch")
def corpus_fetch(
    dest: Annotated[Path, typer.Argument(help="Where to save the raw pages.")],
    ref: Annotated[str, typer.Option(help="microsoft/playwright commit.")] = (
        "9a82788d83cf91d8262e65a432b9bf93dc5418a7"
    ),
) -> None:  # pragma: no cover - network
    """Download the raw doc pages (and the Apache-2.0 LICENSE) at a pinned commit."""
    import httpx

    dest.mkdir(parents=True, exist_ok=True)
    base = f"https://raw.githubusercontent.com/microsoft/playwright/{ref}"
    for name in [*DEFAULT_PAGES, "LICENSE"]:
        url = f"{base}/LICENSE" if name == "LICENSE" else f"{base}/docs/src/{name}.md"
        resp = httpx.get(url, timeout=30)
        resp.raise_for_status()
        target = dest / (name if name == "LICENSE" else f"{name}.md")
        target.write_text(resp.text, encoding="utf-8", newline="\n")
    echo(f"fetched {len(DEFAULT_PAGES)} pages at {ref[:12]} into {dest.as_posix()}")
