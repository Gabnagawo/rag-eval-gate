"""Adapters that let RAGAS and DeepEval use the local Ollama judge.

Both frameworks normally call hosted models through their own clients. Routing them
through :class:`OllamaClient` keeps evaluation free, sends the same ``num_ctx`` as
every other request, serializes calls (concurrency 1 on a shared server) and asks
Ollama for JSON that matches each framework's response schema.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, TypeVar

from pydantic import BaseModel

from rag_eval_gate.ollama import OllamaClient

os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "YES")
os.environ.setdefault("DEEPEVAL_UPDATE_WARNING_OPT_IN", "NO")

from deepeval.models import DeepEvalBaseLLM
from ragas.embeddings.base import BaseRagasEmbedding
from ragas.llms.base import InstructorBaseRagasLLM

T = TypeVar("T", bound=BaseModel)


def structured[T: BaseModel](client: OllamaClient, model: str, prompt: str, schema: type[T]) -> T:
    """One judge call constrained to ``schema``'s JSON schema, parsed with pydantic."""
    result = client.chat(
        model, [{"role": "user", "content": prompt}], schema=schema.model_json_schema()
    )
    return schema.model_validate_json(result.text)


class OllamaRagasLLM(InstructorBaseRagasLLM):
    def __init__(self, client: OllamaClient, model: str) -> None:
        self.client = client
        self.model = model

    def generate(self, prompt: str, response_model: type[T]) -> T:
        return structured(self.client, self.model, prompt, response_model)

    async def agenerate(self, prompt: str, response_model: type[T]) -> T:
        return await asyncio.to_thread(self.generate, prompt, response_model)


class OllamaRagasEmbeddings(BaseRagasEmbedding):
    """Symmetric similarity (question vs generated question): same prefix on both sides."""

    def __init__(self, client: OllamaClient, model: str, prefix: str = "search_query: ") -> None:
        super().__init__()
        self.client = client
        self.model = model
        self.prefix = prefix

    def embed_text(self, text: str, **kwargs: Any) -> list[float]:
        return self.client.embed(self.model, self.prefix + text)

    async def aembed_text(self, text: str, **kwargs: Any) -> list[float]:
        return await asyncio.to_thread(self.embed_text, text)


class OllamaDeepEvalLLM(DeepEvalBaseLLM):
    def __init__(self, client: OllamaClient, model: str) -> None:
        self.client = client
        self.model_id = model
        super().__init__(model)

    def load_model(self, *args: Any, **kwargs: Any) -> OllamaDeepEvalLLM:
        return self

    def generate(self, prompt: str, schema: type[BaseModel] | None = None, **kwargs: Any) -> Any:
        if schema is not None:
            return structured(self.client, self.model_id, prompt, schema)
        return self.client.chat(self.model_id, [{"role": "user", "content": prompt}]).text

    async def a_generate(
        self, prompt: str, schema: type[BaseModel] | None = None, **kwargs: Any
    ) -> Any:
        return await asyncio.to_thread(self.generate, prompt, schema)

    def get_model_name(self, *args: Any, **kwargs: Any) -> str:
        return f"ollama/{self.model_id}"
