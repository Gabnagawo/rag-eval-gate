"""Answer generators (``LLM_PROVIDER``) and embedders.

The generator is the model under test and can be Ollama (default), Anthropic or
OpenAI; the SDKs for the hosted providers are optional extras imported lazily.
Judging and embeddings always go through Ollama, so evaluation is free and local.
"""

from __future__ import annotations

import hashlib
import math
import re
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from rag_eval_gate.config import Settings
from rag_eval_gate.ollama import OllamaClient, OllamaError


class GenerationError(RuntimeError):
    pass


@dataclass(frozen=True)
class Generation:
    text: str
    model: str
    latency_s: float


class Generator(Protocol):
    model: str

    def generate(self, system: str, user: str, max_tokens: int) -> Generation: ...


class Embedder(Protocol):
    model: str

    def embed(self, text: str) -> list[float]: ...


class OllamaGenerator:
    def __init__(self, client: OllamaClient, model: str) -> None:
        self.client = client
        self.model = model

    def generate(self, system: str, user: str, max_tokens: int) -> Generation:
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        try:
            result = self.client.chat(self.model, messages, max_tokens=max_tokens)
        except OllamaError as exc:
            raise GenerationError(str(exc)) from exc
        return Generation(result.text, self.model, result.latency_s)


class AnthropicGenerator:
    def __init__(self, model: str, api_key: str | None = None, client: Any = None) -> None:
        if client is None:
            try:
                import anthropic
            except ImportError as exc:  # pragma: no cover - depends on the extra
                raise GenerationError("install the extra: uv sync --extra anthropic") from exc
            client = anthropic.Anthropic(api_key=api_key, max_retries=3)
        self.client = client
        self.model = model

    def generate(self, system: str, user: str, max_tokens: int) -> Generation:
        start = time.perf_counter()
        try:
            msg = self.client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
        except Exception as exc:
            raise GenerationError(f"anthropic: {exc}") from exc
        text = "".join(getattr(b, "text", "") for b in msg.content if b.type == "text")
        return Generation(text.strip(), self.model, round(time.perf_counter() - start, 3))


class OpenAIGenerator:
    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        base_url: str | None = None,
        client: Any = None,
    ) -> None:
        if client is None:
            try:
                import openai
            except ImportError as exc:  # pragma: no cover - depends on the extra
                raise GenerationError("install the extra: uv sync --extra openai") from exc
            client = openai.OpenAI(api_key=api_key, base_url=base_url, max_retries=3)
        self.client = client
        self.model = model

    def generate(self, system: str, user: str, max_tokens: int) -> Generation:
        start = time.perf_counter()
        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                max_tokens=max_tokens,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            )
        except Exception as exc:
            raise GenerationError(f"openai: {exc}") from exc
        text = resp.choices[0].message.content or ""
        return Generation(text.strip(), self.model, round(time.perf_counter() - start, 3))


class FakeGenerator:
    """Answers with the first sentence of the first context block (tests and dry runs)."""

    model = "fake"

    def generate(self, system: str, user: str, max_tokens: int) -> Generation:
        match = re.search(r"\[1\][^\n]*\n(.+?)(?:\n\n|\n\[2\]|$)", user, flags=re.DOTALL)
        text = match.group(1).strip().split(". ")[0] if match else "I don't know."
        return Generation(text, self.model, 0.0)


class OllamaEmbedder:
    def __init__(self, client: OllamaClient, model: str) -> None:
        self.client = client
        self.model = model

    def embed(self, text: str) -> list[float]:
        return self.client.embed(self.model, text)


class HashEmbedder:
    """Deterministic bag-of-words embedder for tests: no model, no network."""

    model = "hash-bow"

    def __init__(self, dims: int = 256) -> None:
        self.dims = dims

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dims
        for token in re.findall(r"[a-z0-9_]+", text.lower()):
            if token in {"search_query", "search_document"}:
                continue
            bucket = int(hashlib.md5(token.encode(), usedforsecurity=False).hexdigest(), 16)
            vec[bucket % self.dims] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]


def build_generator(settings: Settings, client: OllamaClient, fallback_model: str) -> Generator:
    model = settings.generator_model(fallback_model)
    match settings.llm_provider:
        case "ollama":
            return OllamaGenerator(client, model)
        case "anthropic":
            key = settings.anthropic_api_key
            return AnthropicGenerator(model, key.get_secret_value() if key else None)
        case "openai":
            key = settings.openai_api_key
            return OpenAIGenerator(
                model, key.get_secret_value() if key else None, settings.openai_base_url
            )
        case "fake":
            return FakeGenerator()
    raise ValueError(settings.llm_provider)  # pragma: no cover


def build_client(settings: Settings) -> OllamaClient:
    return OllamaClient(
        settings.ollama_host,
        num_ctx=settings.ollama_num_ctx,
        think=settings.ollama_think,
        seed=settings.llm_seed,
        timeout_s=settings.llm_timeout_s,
        retries=settings.llm_retries,
        reload_on_fault=settings.ollama_reload_on_fault,
    )


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0
