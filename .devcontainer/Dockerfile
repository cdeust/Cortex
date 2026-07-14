# Cortex development container — one-command environment for contributors
# and for `claude` running inside an isolated devcontainer (issue #118).
#
# Reuses (does not reinvent) the production build recipe already validated
# in ../Dockerfile's builder stage: same CPU-only torch pin rationale, same
# `pip install .[postgresql]` base. Docker has no cross-Dockerfile stage
# inheritance without a prebuilt image tag (`FROM <tag>` requires the tag to
# already exist, which `docker compose build` cannot guarantee ordering for
# across two separate Dockerfiles) — so the recipe is duplicated here, not
# FROM-chained. Keep the two in sync; see docs/deployment-scenarios.md
# "Dev container" for the tradeoff.
#
# Build:  docker compose -f .devcontainer/docker-compose.yml build
# (normally invoked by the Dev Containers CLI / VS Code "Reopen in
# Container", never by hand.)

FROM python:3.13-slim

LABEL org.opencontainers.image.source="https://github.com/cdeust/Cortex"
LABEL org.opencontainers.image.description="Cortex development container (issue #118)"

# gcc/libpq-dev: same build deps as ../Dockerfile's builder stage (psycopg
# has no manylinux wheel for every platform this image might run on).
# postgresql-client: scripts/setup_db.py shells out to psql/createdb/
# pg_isready (see that file) — required for postCreateCommand to work.
# git: contributor workflow inside the container.
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

# CPU-only torch wheel: sentence-transformers pulls torch transitively as a
# mandatory base dependency (pyproject.toml); pip's default index resolves
# the full CUDA build (~2GB across torch/cudnn/cusparselt/cublas/etc.) even
# though this container never uses a GPU — identical rationale to
# ../Dockerfile:38-45 and benchmarks/reproduce.sh's own CPU-only builds.
# Versions pinned exactly to this repo's lockfile so the devcontainer
# never silently drifts from what CI/production actually run.
# source: uv.lock (this repo, checked 2026-07-14) — torch==2.11.0,
# sentence-transformers==5.4.1, flashrank==0.2.10.
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir torch==2.11.0 --index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-cache-dir ".[postgresql,codebase]" \
        "sentence-transformers==5.4.1" \
        "flashrank==0.2.10"

# ── Model prewarming AT BUILD TIME ─────────────────────────────────────────
# HF_HOME / XDG_CACHE_HOME point at a durable image path baked into a layer
# — never /tmp. mcp_server/core/reranker.py's module docstring documents
# the exact incident this avoids: FlashRank 0.2.10's own default cache_dir
# IS /tmp, and an ephemeral-fs purge between the download and first use
# caused a silent reranker skip in production (fix 2026-07-11). Baking both
# caches into an image layer means the FIRST recall/remember call in a
# freshly-opened devcontainer never pays (or risks) a cold-start network
# fetch, and never touches /tmp.
ENV HF_HOME=/opt/model-cache/huggingface \
    XDG_CACHE_HOME=/opt/model-cache \
    CORTEX_RUNTIME=cowork

RUN mkdir -p /opt/model-cache && \
    python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')" && \
    python -c "from mcp_server.core.reranker import _ensure_reranker; assert _ensure_reranker() is not None, 'FlashRank prewarm failed at build time'" && \
    chown -R cortex:cortex /opt/model-cache /workspace

USER cortex
