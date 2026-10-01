# source: ADR-0797

#
# source: ADR-0797







#
# Build:  docker compose -f .devcontainer/docker-compose.yml build
# (normally invoked by the Dev Containers CLI / VS Code "Reopen in
# Container", never by hand.)

# source: ADR-0797






FROM python:3.14-slim@sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6

LABEL org.opencontainers.image.source="https://github.com/cdeust/Cortex"
LABEL org.opencontainers.image.description="Cortex development container (issue #118)"

# Build dependencies: gcc/libpq-dev, PostgreSQL client utilities, and git.
# source: ADR-0797
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        libpq-dev \
        postgresql-client \
        git \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 cortex

WORKDIR /workspace

COPY pyproject.toml README.md ./
COPY mcp_server ./mcp_server

# The same uv.lock CI and production resolve from, installed into the
# image's Python as the lock pins it (postgresql + codebase + container,
# CPU-only torch), every artifact checked against the lock's sha256.
# source: ADR-1092
COPY --from=ghcr.io/astral-sh/uv:0.11.3@sha256:90bbb3c16635e9627f49eec6539f956d70746c409209041800a0280b93152823 /uv /usr/local/bin/uv
COPY uv.lock ./
RUN UV_PROJECT_ENVIRONMENT=/usr/local uv sync --locked --inexact --no-cache \
    --no-install-project --no-default-groups \
    --extra postgresql --extra codebase --group container

# source: ADR-0797


RUN pip install --no-cache-dir --no-deps -e .

# source: ADR-0797








ENV HF_HOME=/opt/model-cache/huggingface \
    XDG_CACHE_HOME=/opt/model-cache \
    CORTEX_RUNTIME=cowork

# source: ADR-0797







RUN mkdir -p /opt/model-cache && \
    retry() { \
        label="$1"; shift; \
        for attempt in 1 2 3 4 5; do \
            "$@" && return 0; \
            echo "${label} prewarm attempt ${attempt} failed; retrying in $((attempt * 10))s" >&2; \
            sleep $((attempt * 10)); \
        done; \
        echo "${label} prewarm failed after 5 attempts" >&2; \
        return 1; \
    }; \
    retry HF python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')" && \
    retry FlashRank python -c "from mcp_server.hooks.wiring import wire_composition_root; wire_composition_root(); from mcp_server.core.reranker import _ensure_reranker; assert _ensure_reranker() is not None, 'FlashRank prewarm failed at build time'" && \
    chown -R cortex:cortex /opt/model-cache /workspace

USER cortex
