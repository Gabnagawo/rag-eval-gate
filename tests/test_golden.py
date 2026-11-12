from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from rag_eval_gate.corpus import load_corpus
from rag_eval_gate.golden import GoldenSet, golden_sha256, load_golden
from tests.conftest import ROOT

GOLDEN = ROOT / "eval" / "golden.yaml"


def test_golden_set_size_and_ids() -> None:
    golden = load_golden(GOLDEN)
    assert 25 <= len(golden.items) <= 40
    assert len(golden_sha256(GOLDEN)) == 64


@pytest.mark.parametrize("item", load_golden(GOLDEN).items, ids=lambda i: i.id)
def test_every_answer_is_in_the_corpus(item) -> None:  # type: ignore[no-untyped-def]
    pages = load_corpus(ROOT / "data" / "corpus")
    assert set(item.sources) <= set(pages), f"unknown source page in {item.id}"
    assert item.evidence in pages[item.sources[0]], f"evidence for {item.id} not found"


def test_duplicate_ids_are_rejected() -> None:
    item = {
        "id": "a",
        "question": "q" * 12,
        "reference": "r" * 12,
        "sources": ["x"],
        "evidence": "abc",
    }
    with pytest.raises(ValidationError, match="duplicate"):
        GoldenSet.model_validate({"items": [item, item]})


def test_load_from_tmp(tmp_path: Path) -> None:
    path = tmp_path / "g.yaml"
    path.write_text(
        "items:\n  - {id: x, question: 'What is this thing?', reference: 'A reference.',"
        " sources: [p], evidence: ref}\n",
        encoding="utf-8",
    )
    assert load_golden(path).items[0].id == "x"
