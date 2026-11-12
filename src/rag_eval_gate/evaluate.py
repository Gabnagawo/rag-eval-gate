"""Run the golden set through the pipeline, score every sample and write a results file.

The results file is rewritten after every sample, and ``resume=True`` skips samples
that are already fully scored, so a run interrupted on a busy machine continues where
it stopped instead of starting over.
"""

from __future__ import annotations

import json
import platform
import statistics
import time
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from rag_eval_gate.golden import GoldenItem
from rag_eval_gate.metrics import LOWER_IS_BETTER, RETRIEVAL_METRICS, MetricFn, Sample
from rag_eval_gate.rag import RagAnswer, RagPipeline

RESULTS_SCHEMA_VERSION = 1


class MetricSummary(BaseModel):
    mean: float | None
    n: int
    failed: int
    lower_is_better: bool = False


class RunInfo(BaseModel):
    run_id: str
    profile: str
    started_at: datetime
    finished_at: datetime | None = None
    generator: str
    judge_model: str | None
    embed_model: str
    rag_config: dict[str, Any]
    corpus_sha256: str
    golden_sha256: str
    metrics: list[str]
    versions: dict[str, str] = Field(default_factory=dict)
    platform: str = ""


class Results(BaseModel):
    schema_version: int = RESULTS_SCHEMA_VERSION
    run: RunInfo
    samples: list[dict[str, Any]] = Field(default_factory=list)
    summary: dict[str, MetricSummary] = Field(default_factory=dict)

    def sample_ids(self) -> set[str]:
        return {s["id"] for s in self.samples}


def versions() -> dict[str, str]:
    out = {"python": platform.python_version()}
    for pkg in ("rag-eval-gate", "ragas", "deepeval", "numpy"):
        try:
            out[pkg] = metadata.version(pkg)
        except metadata.PackageNotFoundError:  # pragma: no cover
            out[pkg] = "unknown"
    return out


def summarize(samples: list[dict[str, Any]], metric_names: list[str]) -> dict[str, MetricSummary]:
    out = {}
    for name in metric_names:
        values = [s["metrics"].get(name) for s in samples]
        scored = [v for v in values if v is not None]
        out[name] = MetricSummary(
            mean=round(statistics.fmean(scored), 4) if scored else None,
            n=len(scored),
            failed=len(values) - len(scored),
            lower_is_better=name in LOWER_IS_BETTER,
        )
    return out


def restrict(results: Results, ids: set[str]) -> Results:
    """The same run limited to ``ids``, with its summary recomputed.

    Lets a PR evaluated on a subset of the golden set be compared with a full baseline
    on exactly the same questions.
    """
    samples = [s for s in results.samples if s["id"] in ids]
    return results.model_copy(
        update={"samples": samples, "summary": summarize(samples, results.run.metrics)}
    )


def load_results(path: Path) -> Results:
    return Results.model_validate_json(path.read_text(encoding="utf-8"))


def save_results(results: Results, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(json.loads(results.model_dump_json()), indent=2, ensure_ascii=False)
    path.write_text(text + "\n", encoding="utf-8", newline="\n")


Progress = Callable[[int, int, dict[str, Any]], None]


class Evaluator:
    def __init__(
        self,
        pipeline: RagPipeline,
        metric_fns: dict[str, MetricFn],
        out_path: Path,
        run: RunInfo,
        progress: Progress | None = None,
    ) -> None:
        self.pipeline = pipeline
        self.metric_fns = metric_fns
        self.out_path = out_path
        self.run_info = run
        self.progress = progress

    def run(self, items: list[GoldenItem], resume: bool = False) -> Results:
        results = Results(run=self.run_info)
        if resume and self.out_path.exists():
            previous = load_results(self.out_path)
            if previous.run.rag_config == self.run_info.rag_config:
                names = set(self.metric_fns)
                results.samples = [
                    s
                    for s in previous.samples
                    if names <= {k for k, v in s["metrics"].items() if v is not None}
                ]
                results.run.started_at = previous.run.started_at
        done = results.sample_ids()
        for n, item in enumerate(items, start=1):
            if item.id in done:
                continue
            record = self.score_item(item)
            results.samples.append(record)
            results.samples.sort(key=lambda s: [i.id for i in items].index(s["id"]))
            results.summary = summarize(results.samples, list(self.metric_fns))
            save_results(results, self.out_path)
            if self.progress:
                self.progress(n, len(items), record)
        results.summary = summarize(results.samples, list(self.metric_fns))
        results.run.finished_at = datetime.now(UTC)
        save_results(results, self.out_path)
        return results

    def score_item(self, item: GoldenItem) -> dict[str, Any]:
        if set(self.metric_fns) <= set(RETRIEVAL_METRICS):
            # Retrieval metrics only: skip the (slow, paid) generation step.
            retrieved = self.pipeline.retrieve(item.question)
            answer = RagAnswer(item.question, "", retrieved, 0.0, 0.0)
        else:
            answer = self.pipeline.answer(item.question)
        sample = Sample(
            id=item.id,
            question=item.question,
            reference=item.reference,
            sources=item.sources,
            answer=answer.answer,
            contexts=answer.contexts,
            retrieved_sources=answer.sources,
        )
        timings: dict[str, float] = {}
        for name, fn in self.metric_fns.items():
            start = time.perf_counter()
            try:
                sample.metrics[name] = round(fn(sample), 4)
            except Exception as exc:  # a judge failure must not lose the whole run
                sample.metrics[name] = None
                sample.errors[name] = f"{type(exc).__name__}: {exc}"[:300]
            timings[name] = round(time.perf_counter() - start, 2)
        record = asdict(sample)
        record["retrieved"] = [
            {"id": r.chunk.id, "source": r.chunk.source, "score": round(r.score, 4)}
            for r in answer.retrieved
        ]
        record["timings_s"] = {
            "retrieval": answer.retrieval_s,
            "generation": answer.generation_s,
            **timings,
        }
        return record
