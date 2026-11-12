from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from pydantic import BaseModel

from rag_eval_gate.judges import (
    OllamaDeepEvalLLM,
    OllamaRagasEmbeddings,
    OllamaRagasLLM,
    structured,
)
from rag_eval_gate.metrics import (
    LLMJudge,
    Sample,
    _value,
    hit_rate,
    metric_functions,
    mrr,
)
from rag_eval_gate.ollama import ChatResult


class Verdict(BaseModel):
    verdict: int
    reason: str


class ScriptedClient:
    """Stands in for OllamaClient: answers chat with JSON, embed with a fixed vector."""

    def __init__(self, answers: list[str]) -> None:
        self.answers = answers
        self.chats: list[dict[str, Any]] = []
        self.embeds: list[str] = []

    def chat(self, model: str, messages: list[dict[str, str]], **kwargs: Any) -> ChatResult:
        self.chats.append({"model": model, "messages": messages, **kwargs})
        return ChatResult(self.answers.pop(0), 0.1, 1, 1, 0)

    def embed(self, model: str, text: str) -> list[float]:
        self.embeds.append(text)
        return [1.0, 0.0]


def sample(**kw: Any) -> Sample:
    base = {
        "id": "s",
        "question": "How do I take a full page screenshot?",
        "reference": "page.screenshot(full_page=True)",
        "sources": ["screenshots"],
        "answer": "Use page.screenshot(full_page=True).",
        "contexts": ["page.screenshot(path='a.png', full_page=True)"],
        "retrieved_sources": ["downloads", "screenshots"],
    }
    return Sample(**{**base, **kw})


def test_retrieval_metrics() -> None:
    assert hit_rate(sample()) == 1.0
    assert mrr(sample()) == 0.5
    assert hit_rate(sample(retrieved_sources=["x"])) == 0.0
    assert mrr(sample(retrieved_sources=["x"])) == 0.0


def test_structured_sends_schema_and_parses() -> None:
    client = ScriptedClient([json.dumps({"verdict": 1, "reason": "ok"})])
    out = structured(client, "judge", "is it?", Verdict)  # type: ignore[arg-type]
    assert out == Verdict(verdict=1, reason="ok")
    assert client.chats[0]["schema"]["title"] == "Verdict"
    assert client.chats[0]["messages"] == [{"role": "user", "content": "is it?"}]


def test_ragas_llm_and_embeddings_adapters() -> None:
    client = ScriptedClient([json.dumps({"verdict": 0, "reason": "a"})] * 2)
    llm = OllamaRagasLLM(client, "judge")  # type: ignore[arg-type]
    assert llm.generate("p", Verdict).verdict == 0
    assert asyncio.run(llm.agenerate("p", Verdict)).reason == "a"
    emb = OllamaRagasEmbeddings(client, "nomic")  # type: ignore[arg-type]
    assert emb.embed_text("q") == [1.0, 0.0]
    assert asyncio.run(emb.aembed_text("r")) == [1.0, 0.0]
    assert client.embeds == ["search_query: q", "search_query: r"]


def test_deepeval_adapter() -> None:
    client = ScriptedClient([json.dumps({"verdict": 1, "reason": "b"}), "plain text"])
    model = OllamaDeepEvalLLM(client, "judge")  # type: ignore[arg-type]
    assert model.load_model() is model
    assert model.get_model_name() == "ollama/judge"
    assert model.generate("p", schema=Verdict).verdict == 1
    assert asyncio.run(model.a_generate("p")) == "plain text"


class FakeMetric:
    def __init__(self, value: float | None) -> None:
        self.value = value
        self.calls: list[dict[str, Any]] = []

    def score(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return self


def test_llm_judge_passes_the_right_fields_to_ragas() -> None:
    judge = LLMJudge(ScriptedClient([]), "judge", "nomic")  # type: ignore[arg-type]
    fakes = {
        "faithfulness": FakeMetric(0.9),
        "answer_relevancy": FakeMetric(1.2),  # clamped to 1.0
        "context_precision": FakeMetric(-0.1),  # clamped to 0.0
        "context_recall": FakeMetric(None),
    }
    judge._ragas = dict(fakes)
    s = sample()
    assert judge.faithfulness(s) == 0.9
    assert judge.answer_relevancy(s) == 1.0
    assert judge.context_precision(s) == 0.0
    with pytest.raises(ValueError, match="no score"):
        judge.context_recall(s)
    assert set(fakes["faithfulness"].calls[0]) == {"user_input", "response", "retrieved_contexts"}
    assert set(fakes["answer_relevancy"].calls[0]) == {"user_input", "response"}
    assert set(fakes["context_precision"].calls[0]) == {
        "user_input",
        "reference",
        "retrieved_contexts",
    }
    assert set(fakes["context_recall"].calls[0]) == {
        "user_input",
        "retrieved_contexts",
        "reference",
    }


def test_llm_judge_builds_real_ragas_metrics_lazily() -> None:
    judge = LLMJudge(ScriptedClient([]), "judge", "nomic", relevancy_strictness=2)  # type: ignore[arg-type]
    metric = judge._ragas_metric("answer_relevancy")
    assert type(metric).__name__ == "AnswerRelevancy"
    assert set(judge._ragas) == {
        "faithfulness",
        "answer_relevancy",
        "context_precision",
        "context_recall",
    }


def test_llm_judge_hallucination_through_deepeval() -> None:
    # DeepEval 4.x: one verdict per context, score = share of "yes" (agrees), higher is better.
    two = sample(contexts=["a", "b"])
    verdicts = {"verdicts": [{"verdict": "yes", "reason": "ok"}, {"verdict": "no", "reason": "x"}]}
    client = ScriptedClient([json.dumps(verdicts)])
    judge = LLMJudge(client, "judge", "nomic")  # type: ignore[arg-type]
    assert judge.hallucination(two) == 0.5
    assert client.chats[0]["model"] == "judge"


def test_metric_functions_resolution() -> None:
    assert list(metric_functions(["mrr", "hit_rate"], None)) == ["mrr", "hit_rate"]
    judge = LLMJudge(ScriptedClient([]), "j", "e")  # type: ignore[arg-type]
    assert "hallucination" in metric_functions(["hallucination"], judge)
    with pytest.raises(ValueError, match="unknown metric"):
        metric_functions(["bleu"], None)
    with pytest.raises(ValueError, match="need an LLM judge"):
        metric_functions(["faithfulness"], None)


def test_value_accepts_plain_numbers() -> None:
    assert _value(0.25) == 0.25
