"""A small, conservative Ollama client shared by the generator, the judges and the embedder.

It is written for a server shared with other processes:

- one request at a time per process (a lock), whatever the caller's concurrency;
- the same ``num_ctx`` on every chat request, so the model is never reloaded;
- embeddings one input per request, with all-zero vectors rejected and retried
  (batched requests to a busy Ollama 0.40 returned corrupted rows);
- retries with exponential backoff and a new seed per retry.
"""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import httpx

_THINK_RE = re.compile(r"<think>.*?</think>", flags=re.DOTALL)


class OllamaError(RuntimeError):
    """Ollama did not return a usable answer after retries."""


@dataclass(frozen=True)
class ChatResult:
    text: str
    latency_s: float
    prompt_tokens: int | None
    completion_tokens: int | None
    retries: int


class OllamaClient:
    def __init__(
        self,
        host: str = "http://localhost:11434",
        *,
        num_ctx: int = 16384,
        think: bool = False,
        seed: int | None = 42,
        timeout_s: float = 300.0,
        retries: int = 4,
        backoff_s: float = 5.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.host = host.rstrip("/")
        self.num_ctx = num_ctx
        self.think = think
        self.seed = seed
        self.retries = retries
        self.backoff_s = backoff_s
        self.client = client or httpx.Client(timeout=timeout_s)
        self._lock = threading.Lock()
        self.calls = 0

    def options(self) -> dict[str, Any]:
        # Qwen3 model card: non-thinking T=0.7/top_p=0.8, thinking T=0.6/top_p=0.95, top_k=20,
        # min_p=0; presence_penalty curbs the repetition loops quantized builds fall into.
        return {
            "num_ctx": self.num_ctx,
            "temperature": 0.6 if self.think else 0.7,
            "top_p": 0.95 if self.think else 0.8,
            "top_k": 20,
            "min_p": 0,
            "presence_penalty": 1.5,
        }

    def _post(self, path: str, payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
        last_error = "no attempt made"
        for attempt in range(self.retries + 1):
            if "options" in payload and self.seed is not None:
                payload["options"]["seed"] = self.seed + attempt
            try:
                with self._lock:
                    self.calls += 1
                    resp = self.client.post(f"{self.host}{path}", json=payload)
            except httpx.HTTPError as exc:
                last_error = f"{type(exc).__name__}: {exc}"
            else:
                if resp.status_code == 200:
                    return resp.json(), attempt
                last_error = f"HTTP {resp.status_code}: {resp.text[:300]}"
                if resp.status_code < 500 and resp.status_code != 429:
                    raise OllamaError(f"ollama {path} {last_error}")
            if attempt < self.retries:
                time.sleep(self.backoff_s * 2**attempt)
        raise OllamaError(f"ollama {path} failed after {self.retries + 1} attempts: {last_error}")

    def chat(
        self,
        model: str,
        messages: Sequence[dict[str, str]],
        *,
        schema: dict[str, Any] | None = None,
        max_tokens: int | None = None,
    ) -> ChatResult:
        """Chat completion; with ``schema`` the answer is constrained to that JSON schema."""
        start = time.perf_counter()
        options = self.options()
        if max_tokens:
            options["num_predict"] = max_tokens
        payload: dict[str, Any] = {
            "model": model,
            "messages": list(messages),
            "stream": False,
            "think": self.think,
            "options": options,
        }
        if schema is not None:
            payload["format"] = schema
        for empty_retry in range(2):
            data, retries = self._post("/api/chat", payload)
            text = _THINK_RE.sub("", str(data.get("message", {}).get("content") or "")).strip()
            if text:
                return ChatResult(
                    text=text,
                    latency_s=round(time.perf_counter() - start, 3),
                    prompt_tokens=data.get("prompt_eval_count"),
                    completion_tokens=data.get("eval_count"),
                    retries=retries + empty_retry,
                )
        raise OllamaError(f"ollama returned an empty completion for {model}")

    def embed(self, model: str, text: str) -> list[float]:
        """One input per request; an all-zero vector is treated as a failed request."""
        for _ in range(self.retries + 1):
            data, _retries = self._post("/api/embed", {"model": model, "input": text})
            vectors = data.get("embeddings") or []
            if vectors and any(vectors[0]):
                return [float(x) for x in vectors[0]]
            time.sleep(self.backoff_s)
        raise OllamaError(f"ollama returned no usable embedding from {model}")
