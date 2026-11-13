# Linux/macOS/CI. On Windows run the `uv run ...` commands shown in the README.
.PHONY: install lint format typecheck test index ask demo eval gate offline docker clean

PROFILE ?= local

install:
	uv sync

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff format .
	uv run ruff check --fix .

typecheck:
	uv run mypy

test:
	uv run pytest

# Everything below needs Ollama with qwen3:8b and nomic-embed-text, except `offline`.
index:
	uv run rag-gate index

ask:
	uv run rag-gate ask "How do I wait for a popup window opened by a click?"

# The CI profile (8 questions) followed by the gate, as the PR workflow runs it.
demo:
	uv run rag-gate eval --profile ci --out results/demo.json
	uv run rag-gate gate results/demo.json --baseline docs/results/baseline.json

eval:
	uv run rag-gate eval --profile $(PROFILE) --out results/eval.json --resume

gate:
	uv run rag-gate gate results/eval.json --baseline docs/results/baseline.json

# Retrieval metrics with hash embeddings and a fake generator: no model needed.
offline:
	uv run rag-gate eval --offline --out results/offline.json

docker:
	docker build -t rag-eval-gate .

clean:
	rm -rf results .cache .pytest_cache .ruff_cache .mypy_cache .coverage coverage.xml htmlcov
