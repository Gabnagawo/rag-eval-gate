"""The quality gate: compare a results file with the thresholds in ``eval.yaml``.

The gate fails when a metric breaks its threshold, when a metric has no scored
sample, or when more than ``max_failed_fraction`` of a metric's judge calls failed
(a gate that silently ignores broken judges would pass anything).
"""

from __future__ import annotations

from dataclasses import dataclass

from rag_eval_gate.config import Threshold
from rag_eval_gate.evaluate import Results

MAX_FAILED_FRACTION = 0.2


@dataclass(frozen=True)
class Check:
    metric: str
    value: float | None
    threshold: Threshold
    passed: bool
    reason: str
    baseline: float | None = None

    @property
    def bound(self) -> str:
        if self.threshold.min is not None and self.threshold.max is not None:
            return f"{self.threshold.min:.2f} to {self.threshold.max:.2f}"
        if self.threshold.min is not None:
            return f">= {self.threshold.min:.2f}"
        return f"<= {self.threshold.max:.2f}"


@dataclass(frozen=True)
class GateResult:
    checks: list[Check]
    profile: str
    samples: int

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)


def evaluate_gate(
    results: Results,
    thresholds: dict[str, Threshold],
    baseline: Results | None = None,
    max_failed_fraction: float = MAX_FAILED_FRACTION,
) -> GateResult:
    checks = []
    for metric, threshold in thresholds.items():
        summary = results.summary.get(metric)
        base = baseline.summary.get(metric) if baseline else None
        base_value = base.mean if base else None
        if summary is None or summary.mean is None:
            checks.append(Check(metric, None, threshold, False, "not measured", base_value))
            continue
        total = summary.n + summary.failed
        value = summary.mean
        reasons = []
        if threshold.min is not None and value < threshold.min:
            reasons.append(f"below {threshold.min:.2f}")
        if threshold.max is not None and value > threshold.max:
            reasons.append(f"above {threshold.max:.2f}")
        if total and summary.failed / total > max_failed_fraction:
            reasons.append(f"{summary.failed}/{total} judge calls failed")
        checks.append(
            Check(metric, value, threshold, not reasons, "; ".join(reasons) or "ok", base_value)
        )
    return GateResult(checks, results.run.profile, len(results.samples))


def render_markdown(result: GateResult, results: Results, baseline: Results | None = None) -> str:
    """The PR comment: a verdict line, one row per metric, and how the run was made."""
    verdict = "passed" if result.passed else "failed"
    icon = "✅" if result.passed else "❌"
    run = results.run
    lines = [
        "<!-- rag-eval-gate -->",
        f"### {icon} RAG eval gate {verdict}",
        "",
        f"Profile `{result.profile}`, {result.samples} golden questions, generator "
        f"`{run.generator}`, judge `{run.judge_model}`, embeddings `{run.embed_model}`, "
        f"top_k {run.rag_config.get('top_k')}, chunk_size {run.rag_config.get('chunk_size')}.",
        "",
    ]
    header = "| Metric | Value | Threshold | Status |"
    sep = "|---|---|---|---|"
    if baseline is not None:
        header = "| Metric | Baseline | This PR | Δ | Threshold | Status |"
        sep = "|---|---|---|---|---|---|"
    lines += [header, sep]
    for c in result.checks:
        value = f"{c.value:.3f}" if c.value is not None else "n/a"
        status = "pass" if c.passed else f"**FAIL** ({c.reason})"
        if baseline is not None:
            base = f"{c.baseline:.3f}" if c.baseline is not None else "n/a"
            delta = (
                f"{c.value - c.baseline:+.3f}"
                if c.value is not None and c.baseline is not None
                else "n/a"
            )
            lines.append(f"| {c.metric} | {base} | {value} | {delta} | {c.bound} | {status} |")
        else:
            lines.append(f"| {c.metric} | {value} | {c.bound} | {status} |")
    lines += [
        "",
        "Thresholds live in `eval.yaml`; the pipeline under test is `rag.yaml`. "
        "All metrics are higher-is-better (DeepEval 4.x scores hallucination as agreement).",
    ]
    return "\n".join(lines) + "\n"
