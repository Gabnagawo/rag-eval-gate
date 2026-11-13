"""A small, conservative Ollama client shared by the generator, the judges and the embedder.

It is written for a server shared with other processes:

- one request at a time per process (a lock), whatever the caller's concurrency;
- the same ``num_ctx`` on every chat request, so the model is never reloaded;
- embeddings one input per request, with all-zero vectors rejected and retried
  (batched requests to a busy Ollama 0.40 returned corrupted rows);
- retries with exponential backoff and a new seed per retry;
- an empty or aborted completion is retried with a new seed and, for structured output,
  falls back to JSON mode and then to an unconstrained request (see ``chat``).
"""

from __future__ import annotations

import json
import re
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import httpx

_THINK_RE = re.compile(r"<think>.*?</think>", flags=re.DOTALL)
_SCHEMA_INSTRUCTION = (
    "Respond with a single JSON object that conforms to this JSON schema. "
    "Output only the JSON object, with no code fence and no other text."
)


def extract_json_object(text: str) -> str | None:
    """The outermost ``{...}`` of ``text`` if it parses as a JSON object, else None."""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    candidate = text[start : end + 1]
    try:
        parsed = json.loads(candidate)
    except ValueError:
        return None
    return candidate if isinstance(parsed, dict) else None


# Ollama's HTTP 500 body when it stops a generation that repeats one token.
_REPEAT_ABORT = "token repeat limit reached"
# Options for the unconstrained fallback: a mild repeat penalty against the loop that
# triggers the abort, and a cap so a runaway answer cannot fill the context.
FALLBACK_REPEAT_PENALTY = 1.15
FALLBACK_MAX_TOKENS = 1024


class OllamaError(RuntimeError):
    """Ollama did not return a usable answer after retries."""


class OllamaAbortedError(OllamaError):
    """Ollama stopped the generation itself (token repeat limit).

    The same request fails the same way, so the caller changes it instead of waiting.
    """


@dataclass(frozen=True)
class ChatResult:
    text: str
    latency_s: float
    prompt_tokens: int | None
    completion_tokens: int | None
    retries: int
    # True when the JSON came from the unconstrained fallback, not from `format`.
    schema_fallback: bool = False


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
        self.empty_completions = 0
        self.aborted_completions = 0
        self.schema_fallbacks = 0

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

    def _post(
        self, path: str, payload: dict[str, Any], seed_offset: int = 0
    ) -> tuple[dict[str, Any], int]:
        last_error = "no attempt made"
        for attempt in range(self.retries + 1):
            if "options" in payload and self.seed is not None:
                payload["options"]["seed"] = self.seed + seed_offset + attempt
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
                if _REPEAT_ABORT in resp.text:
                    raise OllamaAbortedError(f"ollama {path} {last_error}")
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
        """Chat completion; with ``schema`` the answer is constrained to that JSON schema.

        Two server-side failures were observed on a shared Ollama 0.40 with qwen3:8b:

        - HTTP 200 with an empty message. llama-server raised "Unexpected empty grammar
          stack after accepting piece" on the first sampled token of a ``format``
          request; a retry with the same seed hit the same cached state and failed again.
        - HTTP 500 "prediction aborted, token repeat limit reached", on the unconstrained
          request that replaced a failing ``format`` request, five seeds in a row.

        So a request is tried in steps, each with a new seed, until one gives an answer:

        1. as asked, twice;
        2. structured only: JSON mode (``format: "json"``) with the schema in the prompt;
        3. structured only: no ``format``, the schema in the prompt, a mild repeat
           penalty and a token cap, twice.

        Steps 2 and 3 count only if the answer contains a parseable JSON object. The
        caller still validates the JSON against its own model.
        """
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
        steps: list[tuple[dict[str, Any], bool]] = [(payload, False), (payload, False)]
        if schema is not None:
            payload["format"] = schema
            json_mode = self._with_schema_in_prompt(payload, schema)
            json_mode["format"] = "json"
            free = self._with_schema_in_prompt(payload, schema)
            free["options"]["repeat_penalty"] = FALLBACK_REPEAT_PENALTY
            free["options"]["num_predict"] = min(
                options.get("num_predict", FALLBACK_MAX_TOKENS), FALLBACK_MAX_TOKENS
            )
            steps += [(json_mode, True), (free, True), (free, True)]

        retries = 0
        problems: list[str] = []
        for step, (request, fallback) in enumerate(steps):
            try:
                data, post_retries = self._post("/api/chat", request, seed_offset=step)
            except OllamaAbortedError:
                self.aborted_completions += 1
                problems.append("aborted (token repeat limit)")
                continue
            retries += post_retries
            text = self._text(data)
            if not text:
                self.empty_completions += 1
                problems.append(f"empty completion (done_reason={data.get('done_reason')!r})")
                continue
            if not fallback:
                return self._result(text, data, start, retries + step)
            found = extract_json_object(text)
            if found is not None:
                self.schema_fallbacks += 1
                return self._result(found, data, start, retries + step, fallback=True)
            problems.append("no JSON object in the fallback answer")
        raise OllamaError(f"ollama gave no usable completion for {model}: {'; '.join(problems)}")

    @staticmethod
    def _text(data: dict[str, Any]) -> str:
        return _THINK_RE.sub("", str(data.get("message", {}).get("content") or "")).strip()

    @staticmethod
    def _result(
        text: str, data: dict[str, Any], start: float, retries: int, fallback: bool = False
    ) -> ChatResult:
        return ChatResult(
            text=text,
            latency_s=round(time.perf_counter() - start, 3),
            prompt_tokens=data.get("prompt_eval_count"),
            completion_tokens=data.get("eval_count"),
            retries=retries,
            schema_fallback=fallback,
        )

    @staticmethod
    def _with_schema_in_prompt(payload: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
        """A copy of the request without ``format``; the schema goes into the last message."""
        messages = [dict(m) for m in payload["messages"]]
        instruction = f"{_SCHEMA_INSTRUCTION}\n{json.dumps(schema)}"
        if messages:
            messages[-1]["content"] = f"{messages[-1]['content']}\n\n{instruction}"
        else:
            messages.append({"role": "user", "content": instruction})
        request = {k: v for k, v in payload.items() if k != "format"}
        request["messages"] = messages
        request["options"] = dict(payload["options"])
        return request

    def embed(self, model: str, text: str) -> list[float]:
        """One input per request; an all-zero vector is treated as a failed request."""
        for _ in range(self.retries + 1):
            data, _retries = self._post("/api/embed", {"model": model, "input": text})
            vectors = data.get("embeddings") or []
            if vectors and any(vectors[0]):
                return [float(x) for x in vectors[0]]
            time.sleep(self.backoff_s)
        raise OllamaError(f"ollama returned no usable embedding from {model}")
