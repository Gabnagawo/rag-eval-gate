from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from rag_eval_gate.config import RagConfig
from rag_eval_gate.llm import FakeGenerator, HashEmbedder
from rag_eval_gate.rag import RagPipeline, VectorIndex, format_context


class CountingEmbedder(HashEmbedder):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def embed(self, text: str) -> list[float]:
        self.calls += 1
        return super().embed(text)


def test_index_is_cached_per_config(rag_cfg: RagConfig, tmp_path: Path) -> None:
    emb = CountingEmbedder()
    first = VectorIndex.build(rag_cfg, emb, cache_dir=tmp_path / "cache")
    n = emb.calls
    assert n == len(first.chunks)
    second = VectorIndex.build(rag_cfg, emb, cache_dir=tmp_path / "cache")
    assert emb.calls == n
    np.testing.assert_allclose(first.vectors, second.vectors)
    other = rag_cfg.model_copy(update={"chunk_size": 300})
    VectorIndex.build(other, emb, cache_dir=tmp_path / "cache")
    assert emb.calls > n
    assert len(list((tmp_path / "cache").glob("*.npy"))) == 2


def test_index_without_cache_and_shape_check(rag_cfg: RagConfig) -> None:
    idx = VectorIndex.build(rag_cfg, HashEmbedder(), cache_dir=None)
    assert idx.vectors.shape[0] == len(idx.chunks)
    with pytest.raises(ValueError, match="one vector per chunk"):
        VectorIndex(idx.chunks, idx.vectors[:1])


def test_pipeline_retrieves_relevant_page_and_answers(rag_cfg: RagConfig) -> None:
    emb = HashEmbedder()
    idx = VectorIndex.build(rag_cfg, emb, cache_dir=None)
    pipeline = RagPipeline(idx, emb, FakeGenerator(), rag_cfg)
    answer = pipeline.answer("What happens to downloaded files when the context is closed?")
    assert answer.sources[0] == "downloads"
    assert len(answer.retrieved) == 2
    assert answer.contexts[0] == answer.retrieved[0].chunk.text
    assert "deleted" in answer.answer
    assert format_context(answer.retrieved).startswith("[1] (downloads: Downloads > Introduction)")
