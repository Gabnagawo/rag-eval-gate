# rag-eval-gate: RAG pipeline + RAGAS/DeepEval quality gate.
#
#   docker build -t rag-eval-gate .
#   # Ollama on the host:
#   docker run --rm -e OLLAMA_HOST=http://host.docker.internal:11434 \
#     -v "$PWD/results:/app/results" rag-eval-gate eval --profile ci --out results/ci.json
FROM python:3.12-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:0.12.10 /uv /uvx /bin/

RUN useradd --create-home --uid 10001 rag

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    DEEPEVAL_TELEMETRY_OPT_OUT=YES

COPY pyproject.toml uv.lock README.md LICENSE ./
RUN uv sync --locked --no-dev --no-install-project
COPY src ./src
COPY data ./data
COPY eval ./eval
COPY rag.yaml eval.yaml ./
RUN uv sync --locked --no-dev && chown -R rag:rag /app

USER rag
ENV PATH="/app/.venv/bin:$PATH"

ENTRYPOINT ["rag-gate"]
CMD ["--help"]
