"""Configuration: environment (models, endpoints) plus two YAML files.

``rag.yaml`` describes the pipeline under test (chunking, retrieval, prompt), so a
pull request that changes retrieval shows up as a diff of that file. ``eval.yaml``
describes the evaluation: golden set, metric thresholds and run profiles.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ProviderName = Literal["ollama", "anthropic", "openai", "fake"]
DEFAULT_MODELS = {"ollama": "qwen3:8b", "anthropic": "claude-sonnet-5-5", "fake": "fake"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    llm_provider: ProviderName = Field(default="ollama", alias="LLM_PROVIDER")
    llm_model: str | None = Field(default=None, alias="LLM_MODEL")
    judge_model: str | None = Field(default=None, alias="JUDGE_MODEL")
    embed_model: str | None = Field(default=None, alias="EMBED_MODEL")
    llm_timeout_s: float = Field(default=300.0, gt=0, alias="LLM_TIMEOUT_S")
    llm_retries: int = Field(default=4, ge=0, le=10, alias="LLM_RETRIES")
    llm_seed: int | None = Field(default=42, alias="LLM_SEED")

    ollama_host: str = Field(default="http://localhost:11434", alias="OLLAMA_HOST")
    # Same value for every client of a shared server, or Ollama reloads the model.
    ollama_num_ctx: int = Field(default=16384, ge=2048, alias="OLLAMA_NUM_CTX")
    ollama_think: bool = Field(default=False, alias="OLLAMA_THINK")

    anthropic_api_key: SecretStr | None = Field(default=None, alias="ANTHROPIC_API_KEY")
    openai_api_key: SecretStr | None = Field(default=None, alias="OPENAI_API_KEY")
    openai_base_url: str | None = Field(default=None, alias="OPENAI_BASE_URL")

    def generator_model(self, fallback: str | None = None) -> str:
        if self.llm_model:
            return self.llm_model
        if self.llm_provider == "ollama" and fallback:
            return fallback
        if self.llm_provider == "openai":
            raise ValueError("LLM_PROVIDER=openai needs LLM_MODEL (no default model is assumed)")
        return DEFAULT_MODELS[self.llm_provider]


class RagConfig(BaseModel):
    """The pipeline under test. Changing this file is what a retrieval PR does."""

    corpus_dir: Path = Path("data/corpus")
    chunk_size: int = Field(default=1200, ge=100)
    chunk_overlap: int = Field(default=150, ge=0)
    top_k: int = Field(default=4, ge=1, le=20)
    embed_model: str = "nomic-embed-text"
    # nomic-embed-text is trained with task prefixes; without them retrieval degrades.
    query_prefix: str = "search_query: "
    document_prefix: str = "search_document: "
    max_answer_tokens: int = Field(default=400, ge=50)

    @model_validator(mode="after")
    def _overlap_below_size(self) -> RagConfig:
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")
        return self


class Threshold(BaseModel):
    min: float | None = Field(default=None, ge=0, le=1)
    max: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def _one_bound(self) -> Threshold:
        if self.min is None and self.max is None:
            raise ValueError("a threshold needs min or max")
        return self


class Profile(BaseModel):
    """Models and sample size for one environment (a laptop vs a CI runner)."""

    generator_model: str = "qwen3:8b"
    judge_model: str = "qwen3:8b"
    limit: int | None = Field(default=None, ge=1, description="Evaluate the first N questions.")
    thresholds: dict[str, Threshold]


class EvalConfig(BaseModel):
    golden_set: Path = Path("eval/golden.yaml")
    metrics: list[str] = Field(
        default_factory=lambda: [
            "hit_rate",
            "mrr",
            "faithfulness",
            "answer_relevancy",
            "context_precision",
            "context_recall",
            "hallucination",
        ]
    )
    profiles: dict[str, Profile]

    def profile(self, name: str) -> Profile:
        try:
            return self.profiles[name]
        except KeyError:
            raise KeyError(f"unknown profile {name!r}; known: {sorted(self.profiles)}") from None


def _load_yaml(path: Path) -> object:
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_rag_config(path: Path = Path("rag.yaml")) -> RagConfig:
    return RagConfig.model_validate(_load_yaml(path) or {})


def load_eval_config(path: Path = Path("eval.yaml")) -> EvalConfig:
    return EvalConfig.model_validate(_load_yaml(path))
