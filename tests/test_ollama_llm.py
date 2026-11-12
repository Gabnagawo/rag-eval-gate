from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from rag_eval_gate.config import Settings
from rag_eval_gate.llm import (
    AnthropicGenerator,
    FakeGenerator,
    GenerationError,
    HashEmbedder,
    OllamaEmbedder,
    OllamaGenerator,
    OpenAIGenerator,
    build_client,
    build_generator,
    cosine,
)
from rag_eval_gate.ollama import OllamaClient, OllamaError


def client_with(responses: list[httpx.Response | Exception], **kwargs: Any):
    requests: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append({"path": request.url.path, **json.loads(request.content)})
        item = responses[min(len(requests), len(responses)) - 1]
        if isinstance(item, Exception):
            raise item
        return item

    http = httpx.Client(transport=httpx.MockTransport(handler))
    return OllamaClient(client=http, backoff_s=0, **kwargs), requests


def chat_ok(text: str) -> httpx.Response:
    return httpx.Response(
        200, json={"message": {"content": text}, "prompt_eval_count": 5, "eval_count": 2}
    )


def test_chat_sends_num_ctx_sampling_schema_and_strips_thinking() -> None:
    client, requests = client_with([chat_ok("<think>x</think> hello")], seed=1)
    result = client.chat(
        "m", [{"role": "user", "content": "hi"}], schema={"type": "object"}, max_tokens=9
    )
    assert (result.text, result.prompt_tokens, result.completion_tokens) == ("hello", 5, 2)
    sent = requests[0]
    assert sent["format"] == {"type": "object"}
    assert sent["options"]["num_ctx"] == 16384
    assert sent["options"]["num_predict"] == 9
    assert sent["options"]["presence_penalty"] == 1.5
    assert sent["options"]["seed"] == 1
    assert sent["think"] is False
    assert client.calls == 1


def test_thinking_options() -> None:
    client, _ = client_with([chat_ok("x")], think=True)
    assert client.options()["temperature"] == 0.6


def test_retries_with_new_seed_then_succeeds() -> None:
    client, requests = client_with(
        [httpx.Response(500, text="busy"), httpx.ConnectError("down"), chat_ok("ok")], seed=10
    )
    assert client.chat("m", []).retries == 2
    assert [r["options"]["seed"] for r in requests] == [10, 11, 12]


def test_gives_up_and_does_not_retry_client_errors() -> None:
    client, requests = client_with([httpx.Response(503, text="x")], retries=1)
    with pytest.raises(OllamaError, match="after 2 attempts"):
        client.chat("m", [])
    client, requests = client_with([httpx.Response(404, text="no model")])
    with pytest.raises(OllamaError, match="HTTP 404"):
        client.chat("m", [])
    assert len(requests) == 1


def test_empty_completion_is_retried_once_then_raises() -> None:
    client, requests = client_with([chat_ok("  ")])
    with pytest.raises(OllamaError, match="empty completion"):
        client.chat("m", [])
    assert len(requests) == 2


def test_embed_one_input_and_rejects_zero_vectors() -> None:
    client, requests = client_with(
        [
            httpx.Response(200, json={"embeddings": [[0.0, 0.0]]}),
            httpx.Response(200, json={"embeddings": [[0.5, 1.0]]}),
        ]
    )
    assert client.embed("e", "text") == [0.5, 1.0]
    assert requests[0] == {"path": "/api/embed", "model": "e", "input": "text"}
    client, _ = client_with([httpx.Response(200, json={"embeddings": []})], retries=1)
    with pytest.raises(OllamaError, match="no usable embedding"):
        client.embed("e", "t")


def test_ollama_generator_and_embedder() -> None:
    client, requests = client_with([chat_ok("answer")])
    gen = OllamaGenerator(client, "qwen3:8b").generate("sys", "user", 50)
    assert (gen.text, gen.model) == ("answer", "qwen3:8b")
    assert requests[0]["messages"][0] == {"role": "system", "content": "sys"}
    failing, _ = client_with([httpx.Response(400, text="bad")])
    with pytest.raises(GenerationError):
        OllamaGenerator(failing, "m").generate("s", "u", 5)
    embed_client, _ = client_with([httpx.Response(200, json={"embeddings": [[1.0]]})])
    assert OllamaEmbedder(embed_client, "nomic").embed("x") == [1.0]


class FakeAnthropic:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.messages = self

    def create(self, **kwargs: Any) -> Any:
        if self.fail:
            raise RuntimeError("overloaded")
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=" hi ")])


class FakeOpenAI:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.chat = SimpleNamespace(completions=self)

    def create(self, **kwargs: Any) -> Any:
        if self.fail:
            raise RuntimeError("rate limited")
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="yo"))])


def test_hosted_generators() -> None:
    assert AnthropicGenerator("c", client=FakeAnthropic()).generate("s", "u", 5).text == "hi"
    assert OpenAIGenerator("g", client=FakeOpenAI()).generate("s", "u", 5).text == "yo"
    with pytest.raises(GenerationError, match="overloaded"):
        AnthropicGenerator("c", client=FakeAnthropic(fail=True)).generate("s", "u", 5)
    with pytest.raises(GenerationError, match="rate limited"):
        OpenAIGenerator("g", client=FakeOpenAI(fail=True)).generate("s", "u", 5)


def test_fake_generator_quotes_first_context() -> None:
    user = "Context:\n[1] (a: b)\nDownloads are deleted. More text.\n\n[2] (c)\nx\n\nQuestion: q"
    assert FakeGenerator().generate("s", user, 5).text == "Downloads are deleted"
    assert FakeGenerator().generate("s", "no context", 5).text == "I don't know."


def test_hash_embedder_is_deterministic_and_normalized() -> None:
    emb = HashEmbedder(dims=64)
    a, b = emb.embed("search_query: full page screenshot"), emb.embed("full page screenshot")
    assert a == b
    assert abs(sum(v * v for v in a) - 1.0) < 1e-9
    assert cosine(a, emb.embed("download file")) < 0.99
    assert cosine([0.0], [1.0]) == 0.0


def settings(**env: Any) -> Settings:
    return Settings.model_validate(env)


def test_build_generator_and_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LLM_MODEL", raising=False)
    s = settings(LLM_PROVIDER="ollama", OLLAMA_NUM_CTX=8192, LLM_SEED=3)
    client = build_client(s)
    assert (client.num_ctx, client.seed) == (8192, 3)
    gen = build_generator(s, client, "qwen3:1.7b")
    assert isinstance(gen, OllamaGenerator)
    assert gen.model == "qwen3:1.7b"
    assert isinstance(build_generator(settings(LLM_PROVIDER="fake"), client, "x"), FakeGenerator)
    with pytest.raises(ValueError, match="needs LLM_MODEL"):
        build_generator(settings(LLM_PROVIDER="openai"), client, "x")
    captured: dict[str, Any] = {}

    def record(model: str, key: str | None = None, *args: Any) -> str:
        captured[model] = key
        return model

    monkeypatch.setattr("rag_eval_gate.llm.AnthropicGenerator", record)
    monkeypatch.setattr("rag_eval_gate.llm.OpenAIGenerator", record)
    build_generator(settings(LLM_PROVIDER="anthropic", ANTHROPIC_API_KEY="k1"), client, "x")
    build_generator(
        settings(LLM_PROVIDER="openai", LLM_MODEL="g", OPENAI_API_KEY="k2"), client, "x"
    )
    assert captured == {"claude-sonnet-5-5": "k1", "g": "k2"}
