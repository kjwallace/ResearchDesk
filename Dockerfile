# One container: the web app, the live route and the embedding model.
#   docker build --build-arg EMBEDDING_MODEL=BAAI/bge-small-en-v1.5 -t triage-app .
#   docker run -p 8000:8000 --env-file .env triage-app
# The embedding model ID is passed at build time (from .env) so the image ships with it.
FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    HF_HOME=/app/.hf

COPY --from=ghcr.io/astral-sh/uv:0.8.15 /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
RUN uv sync --frozen --no-dev

ARG EMBEDDING_MODEL
RUN test -n "$EMBEDDING_MODEL" && \
    uv run python -c "import numpy; from sentence_transformers import SentenceTransformer; SentenceTransformer('${EMBEDDING_MODEL}')"

COPY criteria ./criteria
COPY skills ./skills
COPY instructions ./instructions
COPY tools ./tools
COPY data ./data
COPY tuned ./tuned

EXPOSE 8000
CMD ["uv", "run", "--no-dev", "uvicorn", "triage_app.web.main:app", "--host", "0.0.0.0", "--port", "8000"]
