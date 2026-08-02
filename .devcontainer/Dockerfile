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

# Base image pinned by digest so a rebuild cannot silently pick up a
# different python:3.13-slim. Digest resolved from the multi-arch manifest
# list, so it stays correct on both amd64 and arm64.
#   source: registry-1.docker.io/v2/library/python/manifests/3.13-slim,
#           docker-content-digest header, fetched 2026-07-27.
# Refresh: Dependabot's `docker` ecosystem (.github/dependabot.yml) opens a
# PR when the tag moves; do not hand-edit without re-fetching the header.
FROM python:3.14-slim@sha256:cea0e6040540fb2b965b6e7fb5ffa00871e632eef63719f0ea54bca189ce14a6

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

# Dependencies, hash-pinned from uv.lock via
# scripts/generate_pip_constraints.py — the same lock CI and production
# resolve from, so the devcontainer cannot silently drift from them.
#
# This replaces three hand-copied version pins (torch==2.11.0,
# sentence-transformers==5.4.1, flashrank==0.2.10) that had already drifted:
# the lock had moved to torch 2.13.0 while this file still said 2.11.0. An
# exact version is also not a hash — it names a release, not the bytes the
# index serves for it. The CPU-only torch build is carried by the file (see
# [[tool.uv.index]] in pyproject.toml) rather than by an --index-url flag
# here; the rationale for CPU-only is unchanged and lives in ../Dockerfile.
COPY requirements/devcontainer.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --require-hashes -r /tmp/requirements.txt

# The project itself, editable so a contributor's edits take effect without
# a rebuild. --no-deps because the hashed file above is the complete
# dependency graph; without it pip would re-resolve, unpinned.
RUN pip install --no-cache-dir --no-deps -e .

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

# Both prewarms retry with backoff before failing the build: a transient
# huggingface.co blip must not decide whether the image builds. The bare
# single-shot form of this fetch failed the sibling docker/Dockerfile build on
# PR #337 (CI run 30749502167, 2026-08-02) with "We couldn't connect to
# 'https://huggingface.co'" after 73s. Failing loudly after the retries is
# deliberate — a silently unprewarmed image is the 2026-07-11 FlashRank
# incident again, one layer up.
# source: .github/workflows/ci.yml:131-155 (5 attempts, attempt*10s backoff)
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
    retry FlashRank python -c "from mcp_server.core.reranker import _ensure_reranker; assert _ensure_reranker() is not None, 'FlashRank prewarm failed at build time'" && \
    chown -R cortex:cortex /opt/model-cache /workspace

USER cortex
