# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-11-12

### Added
- Corpus: 24 pages of the Playwright docs (microsoft/playwright `docs/src` at `9a82788`,
  Apache-2.0) reduced to their Python content by `rag-gate corpus fetch` / `corpus build`.
- RAG pipeline configured by `rag.yaml`: heading-aware chunking, `nomic-embed-text`
  embeddings with task prefixes (one input per request, cached index), cosine top-k retrieval
  and a grounded answer prompt. Generator selected by `LLM_PROVIDER` / `LLM_MODEL`: Ollama
  (default `qwen3:8b`), Anthropic and OpenAI as optional lazy extras.
- Golden set of 30 questions with reference answers, answering pages and an evidence string
  that a unit test checks against the corpus.
- Metrics: hit rate and MRR (deterministic), RAGAS faithfulness, answer relevancy, context
  precision and context recall, and DeepEval hallucination, all judged by a local Ollama model
  through adapters that send the same `num_ctx`, serialize calls and request JSON that
  matches each framework's schema.
- `rag-gate eval`: resumable runs that rewrite the results file after every question;
  judge failures are recorded per metric instead of aborting the run.
- `rag-gate gate`: thresholds per profile in `eval.yaml`, a failure when a metric is not
  measured or more than 20 % of its judge calls failed, and a Markdown PR comment with a
  baseline/PR/delta table computed on the same questions.
- GitHub Actions: CI (ruff, mypy, pytest with coverage gate, offline retrieval smoke test,
  hadolint) and the PR gate workflow (Ollama install, `ci` profile, sticky comment, fail on
  breach).
- Local branch `demo/degraded-retriever` with the retrieval change used for the demo PR, and
  real baseline vs degraded results in `docs/results/`.
- Dockerfile and Makefile.

[0.1.0]: https://github.com/Gabnagawo/rag-eval-gate/releases/tag/v0.1.0
