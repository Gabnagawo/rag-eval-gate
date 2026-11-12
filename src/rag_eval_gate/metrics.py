"""Metrics, one function per name, each scoring a single :class:`Sample` in [0, 1].

- ``hit_rate`` and ``mrr`` are deterministic retrieval metrics against the golden
  ``sources`` (no LLM involved).
- ``faithfulness``, ``answer_relevancy``, ``context_precision`` and ``context_recall``
  come from RAGAS.
- ``hallucination`` is DeepEval's HallucinationMetric score, reported unchanged. In
  DeepEval 4.x it is the share of retrieved contexts the answer *agrees* with, so
  higher is better (older DeepEval versions reported the opposite).

The LLM-judged metrics are built lazily so unit tests and retrieval-only runs never
import RAGAS or DeepEval.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from rag_eval_gate.ollama import OllamaClient


@dataclass
class Sample:
    id: str
    question: str
    reference: str
    sources: list[str]
    answer: str
    contexts: list[str]
    retrieved_sources: list[str]
    metrics: dict[str, float | None] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)


MetricFn = Callable[[Sample], float]

# No metric is lower-is-better with DeepEval 4.x; kept for metrics added later.
LOWER_IS_BETTER: frozenset[str] = frozenset()
RETRIEVAL_METRICS = ("hit_rate", "mrr")
RAGAS_METRICS = ("faithfulness", "answer_relevancy", "context_precision", "context_recall")
DEEPEVAL_METRICS = ("hallucination",)
ALL_METRICS = (*RETRIEVAL_METRICS, *RAGAS_METRICS, *DEEPEVAL_METRICS)


def hit_rate(sample: Sample) -> float:
    """1.0 when any retrieved chunk comes from a page that answers the question."""
    return 1.0 if set(sample.retrieved_sources) & set(sample.sources) else 0.0


def mrr(sample: Sample) -> float:
    """Reciprocal rank of the first retrieved chunk from an answering page."""
    for rank, source in enumerate(sample.retrieved_sources, start=1):
        if source in sample.sources:
            return 1.0 / rank
    return 0.0


class LLMJudge:
    """RAGAS and DeepEval metrics backed by the local Ollama judge."""

    def __init__(
        self,
        client: OllamaClient,
        judge_model: str,
        embed_model: str,
        relevancy_strictness: int = 1,
    ) -> None:
        self.client = client
        self.judge_model = judge_model
        self.embed_model = embed_model
        self.relevancy_strictness = relevancy_strictness
        self._ragas: dict[str, Any] = {}

    def _ragas_metric(self, name: str) -> Any:
        if name not in self._ragas:
            from ragas.metrics.collections import (
                AnswerRelevancy,
                ContextPrecision,
                ContextRecall,
                Faithfulness,
            )

            from rag_eval_gate.judges import OllamaRagasEmbeddings, OllamaRagasLLM

            llm = OllamaRagasLLM(self.client, self.judge_model)
            emb = OllamaRagasEmbeddings(self.client, self.embed_model)
            self._ragas = {
                "faithfulness": Faithfulness(llm=llm),
                # strictness=1: one generated question per answer instead of three, to keep
                # a 30-question run on a laptop GPU under an hour.
                "answer_relevancy": AnswerRelevancy(
                    llm=llm, embeddings=emb, strictness=self.relevancy_strictness
                ),
                "context_precision": ContextPrecision(llm=llm),
                "context_recall": ContextRecall(llm=llm),
            }
        return self._ragas[name]

    def faithfulness(self, s: Sample) -> float:
        metric = self._ragas_metric("faithfulness")
        return _value(
            metric.score(user_input=s.question, response=s.answer, retrieved_contexts=s.contexts)
        )

    def answer_relevancy(self, s: Sample) -> float:
        metric = self._ragas_metric("answer_relevancy")
        return _value(metric.score(user_input=s.question, response=s.answer))

    def context_precision(self, s: Sample) -> float:
        metric = self._ragas_metric("context_precision")
        return _value(
            metric.score(
                user_input=s.question, reference=s.reference, retrieved_contexts=s.contexts
            )
        )

    def context_recall(self, s: Sample) -> float:
        metric = self._ragas_metric("context_recall")
        return _value(
            metric.score(
                user_input=s.question, retrieved_contexts=s.contexts, reference=s.reference
            )
        )

    def hallucination(self, s: Sample) -> float:
        from deepeval.metrics import HallucinationMetric
        from deepeval.test_case import LLMTestCase

        from rag_eval_gate.judges import OllamaDeepEvalLLM

        metric = HallucinationMetric(
            threshold=0.5,
            model=OllamaDeepEvalLLM(self.client, self.judge_model),
            async_mode=False,
            include_reason=False,
        )
        metric.measure(LLMTestCase(input=s.question, actual_output=s.answer, context=s.contexts))
        return float(metric.score or 0.0)

    def functions(self) -> dict[str, MetricFn]:
        return {
            "faithfulness": self.faithfulness,
            "answer_relevancy": self.answer_relevancy,
            "context_precision": self.context_precision,
            "context_recall": self.context_recall,
            "hallucination": self.hallucination,
        }


def _value(result: Any) -> float:
    value = getattr(result, "value", result)
    if value is None:
        raise ValueError("the judge returned no score")
    return max(0.0, min(1.0, float(value)))


def metric_functions(names: list[str], judge: LLMJudge | None) -> dict[str, MetricFn]:
    """Resolve metric names to scoring functions, in the requested order."""
    available: dict[str, MetricFn] = {"hit_rate": hit_rate, "mrr": mrr}
    if judge is not None:
        available.update(judge.functions())
    unknown = [n for n in names if n not in ALL_METRICS]
    if unknown:
        raise ValueError(f"unknown metric(s): {unknown}; known: {list(ALL_METRICS)}")
    missing = [n for n in names if n not in available]
    if missing:
        raise ValueError(f"metric(s) {missing} need an LLM judge")
    return {n: available[n] for n in names}
