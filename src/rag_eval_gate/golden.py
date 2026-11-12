"""The golden set: questions with reference answers and the corpus pages that answer them."""

from __future__ import annotations

import hashlib
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator


class GoldenItem(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    question: str = Field(min_length=10)
    reference: str = Field(min_length=10)
    sources: list[str] = Field(min_length=1, description="Corpus page stems with the answer.")
    evidence: str = Field(min_length=3, description="Substring present in the first source.")


class GoldenSet(BaseModel):
    version: int = 1
    items: list[GoldenItem] = Field(min_length=1)

    @field_validator("items")
    @classmethod
    def _unique_ids(cls, items: list[GoldenItem]) -> list[GoldenItem]:
        ids = [i.id for i in items]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"duplicate golden ids: {duplicates}")
        return items


def load_golden(path: Path) -> GoldenSet:
    with path.open(encoding="utf-8") as fh:
        return GoldenSet.model_validate(yaml.safe_load(fh))


def golden_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
