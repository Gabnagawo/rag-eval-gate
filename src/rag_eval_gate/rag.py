"""The RAG pipeline under test: chunk, embed, retrieve top-k by cosine, answer from context."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from rag_eval_gate.config import RagConfig
from rag_eval_gate.corpus import Chunk, chunk_corpus, corpus_sha256, load_corpus
from rag_eval_gate.llm import Embedder, Generator

SYSTEM_PROMPT = """\
You answer questions about Playwright for Python using only the numbered context \
passages from its documentation.
- Base every statement on the context. Do not use outside knowledge.
- If the context does not contain the answer, reply exactly: "The documentation \
provided does not cover this."
- Be concise: at most four sentences, plus one short code snippet only if it helps.
- Use the Python API names (snake_case), as in the context."""


@dataclass(frozen=True)
class Retrieved:
    chunk: Chunk
    score: float


@dataclass(frozen=True)
class RagAnswer:
    question: str
    answer: str
    retrieved: list[Retrieved]
    retrieval_s: float
    generation_s: float

    @property
    def contexts(self) -> list[str]:
        return [r.chunk.text for r in self.retrieved]

    @property
    def sources(self) -> list[str]:
        return [r.chunk.source for r in self.retrieved]


class VectorIndex:
    """Chunks and their normalized embeddings, cached on disk per corpus + config."""

    def __init__(self, chunks: list[Chunk], vectors: np.ndarray) -> None:
        if len(chunks) != len(vectors):
            raise ValueError("one vector per chunk is required")
        self.chunks = chunks
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        self.vectors = vectors / np.where(norms == 0, 1, norms)

    @staticmethod
    def cache_key(corpus_sha: str, cfg: RagConfig, embed_model: str) -> str:
        spec = {
            "corpus": corpus_sha,
            "chunk_size": cfg.chunk_size,
            "overlap": cfg.chunk_overlap,
            "model": embed_model,
            "prefix": cfg.document_prefix,
        }
        return hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()[:16]

    @classmethod
    def build(
        cls,
        cfg: RagConfig,
        embedder: Embedder,
        cache_dir: Path | None = Path(".cache/index"),
        progress: bool = False,
    ) -> VectorIndex:
        pages = load_corpus(cfg.corpus_dir)
        chunks = chunk_corpus(pages, cfg.chunk_size, cfg.chunk_overlap)
        key = cls.cache_key(corpus_sha256(pages), cfg, embedder.model)
        cache = cache_dir / f"{key}.npy" if cache_dir else None
        if cache and cache.exists():
            vectors = np.load(cache)
            if len(vectors) == len(chunks):
                return cls(chunks, vectors)
        rows = []
        for n, chunk in enumerate(chunks, start=1):
            rows.append(embedder.embed(cfg.document_prefix + chunk.embed_text()))
            if progress and n % 50 == 0:  # pragma: no cover - console feedback only
                print(f"  embedded {n}/{len(chunks)} chunks", flush=True)
        vectors = np.asarray(rows, dtype=np.float32)
        if cache:
            cache.parent.mkdir(parents=True, exist_ok=True)
            np.save(cache, vectors)
        return cls(chunks, vectors)

    def search(self, query_vector: list[float], k: int) -> list[Retrieved]:
        q = np.asarray(query_vector, dtype=np.float32)
        q = q / (np.linalg.norm(q) or 1.0)
        scores = self.vectors @ q
        order = np.argsort(-scores, kind="stable")[:k]
        return [Retrieved(self.chunks[i], float(scores[i])) for i in order]


def format_context(retrieved: list[Retrieved]) -> str:
    return "\n\n".join(
        f"[{n}] ({r.chunk.source}: {r.chunk.heading})\n{r.chunk.text}"
        for n, r in enumerate(retrieved, start=1)
    )


class RagPipeline:
    def __init__(
        self, index: VectorIndex, embedder: Embedder, generator: Generator, cfg: RagConfig
    ) -> None:
        self.index = index
        self.embedder = embedder
        self.generator = generator
        self.cfg = cfg

    def retrieve(self, question: str) -> list[Retrieved]:
        vector = self.embedder.embed(self.cfg.query_prefix + question)
        return self.index.search(vector, self.cfg.top_k)

    def answer(self, question: str) -> RagAnswer:
        start = time.perf_counter()
        retrieved = self.retrieve(question)
        retrieval_s = time.perf_counter() - start
        user = f"Context:\n{format_context(retrieved)}\n\nQuestion: {question}"
        generation = self.generator.generate(SYSTEM_PROMPT, user, self.cfg.max_answer_tokens)
        return RagAnswer(
            question=question,
            answer=generation.text,
            retrieved=retrieved,
            retrieval_s=round(retrieval_s, 3),
            generation_s=generation.latency_s,
        )
