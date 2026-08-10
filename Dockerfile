# Cortex MCP server — production image.
#
# Build:    docker build -t cortex:latest .
# Run (DB-less, zero setup — the bare-container / registry-indexer
#       contract, e.g. Glama's per-release microVM):
#           docker run --rm -i cortex:latest
#       tools/list answers with the full standalone tool set on the
#       built-in SQLite backend, no external service, no env vars.
# Run (PostgreSQL, advanced):
#           docker run --rm -i \
#             -e DATABASE_URL=postgresql://user:pass@host:5432/cortex \
#             -e CORTEX_MEMORY_POOL_INTERACTIVE_MAX=16 \
#             cortex:latest
#
# Storage: SQLite by default (zero setup, matches CORTEX_RUNTIME=cowork
# below), or PostgreSQL 15+ with pgvector + pg_trgm when DATABASE_URL is
# set. The image does NOT bundle PostgreSQL; it connects to an external
# instance when one is configured — see mcp_server/infrastructure/
# memory_store.py for the auto/postgresql/sqlite backend-selection logic
# this image relies on (not duplicated here).
#
# Source: docs/program/phase-5-pool-admission-design.md §7.

# Base image pinned by digest so a rebuild cannot silently pick up a
# different python:3.14-slim. Digest resolved from the multi-arch manifest
# list, so it stays correct on both amd64 and arm64.
#   source: registry-1.docker.io/v2/library/python/manifests/3.14-slim,
#           docker-content-digest header, re-verified 2026-07-28.
# Refresh: Dependabot's `docker` ecosystem (.github/dependabot.yml) opens a
# PR when the tag moves; do not hand-edit without re-fetching the header.
FROM python:3.14-slim@sha256:a7fb1e634c4a578f9e0bd6327f11a3cde11b7a9395f48e24360c0988bcc5c2bc AS builder

WORKDIR /build

# Build deps only — stripped from the runtime image.
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install into a virtualenv at a fixed, version-free path instead of the
# interpreter's own site-packages. The runtime stage then copies exactly one
# directory and no COPY anywhere names the Python version, so a base-image
# bump touches only the two FROM lines.
# Root cause this fixes: the runtime stage used to copy
# /usr/local/lib/python3.13/site-packages by literal path. Dependabot bumps
# the FROM tag but cannot know that path exists, so every bump failed the
# blocking Docker Smoke job with `"/usr/local/lib/python3.13/site-packages":
# not found` — observed on #211 (run 30297632187, 3.13 -> 3.14). Bumping the
# literal to 3.14 would fix this PR and re-break the next one.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY pyproject.toml README.md ./
COPY mcp_server ./mcp_server
COPY tests_py ./tests_py

# Dependencies, hash-pinned from uv.lock via
# scripts/generate_pip_constraints.py. Every requirement carries a hash and
# pip refuses anything whose bytes do not match, so this layer is
# reproducible and cannot be substituted at the index.
#
# The CPU-only torch build is part of that file rather than a separate
# `--index-url` flag. sentence-transformers pulls torch as a mandatory base
# dependency, and the default index serves the CUDA build — ~2GB of
# nvidia-cu13-* wheels in an image that never sees a GPU (measured
# 2026-07-12, H2 of the fix/bare-container-contract root-cause report). The
# index is declared once in pyproject.toml's [[tool.uv.index]]; the lock
# records the +cpu wheels and their hashes.
#
# `--upgrade pip build` is gone: it was itself an unpinned install, and
# `build` was never invoked in this file. The base image is digest-pinned,
# so its pip is a known quantity.
COPY requirements/runtime-postgresql.txt requirements/packaging.txt /tmp/
RUN pip install --no-cache-dir --require-hashes -r /tmp/runtime-postgresql.txt

# The project itself, as a built wheel installed with --no-deps.
#
# Not `pip install .[postgresql]` (that re-resolves every dependency,
# unpinned) and not `-e .` (an editable install leaves a .pth pointing at
# /build, which the runtime stage does not copy — the venv would arrive
# broken). A wheel is a self-contained artifact, and --no-deps guarantees
# the hashed set above is the whole dependency graph.
#
# --no-isolation so the build backend is the hashed hatchling from
# packaging.txt rather than one fetched from PyPI mid-build.
RUN pip install --no-cache-dir --require-hashes -r /tmp/packaging.txt && \
    python -m build --wheel --no-isolation --outdir /tmp/dist . && \
    pip install --no-cache-dir --no-deps /tmp/dist/*.whl

# ── Runtime stage ────────────────────────────────────────────────────────

FROM python:3.14-slim@sha256:a7fb1e634c4a578f9e0bd6327f11a3cde11b7a9395f48e24360c0988bcc5c2bc

LABEL org.opencontainers.image.source="https://github.com/cdeust/Cortex"
LABEL org.opencontainers.image.description="Cortex — neuroscience-backed memory system for Claude Code (MCP)"
LABEL org.opencontainers.image.licenses="MIT"

# libpq5 is the runtime side of libpq-dev — psycopg[binary] uses it.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 cortex

# One version-free path carries both the installed packages and the console
# scripts (`hypermnesia-mcp`, `cortex-doctor`) that used to come from
# /usr/local/bin. The venv's bin/python is a symlink into /usr/local, which
# resolves here because this stage pins the same digest as the builder.
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

USER cortex
WORKDIR /home/cortex

# CORTEX_RUNTIME=cowork opts into the store factory's existing permissive
# fallback path (mcp_server/infrastructure/memory_store.py::_construct_store):
# "auto" backend tries PostgreSQL when DATABASE_URL is set, and always
# falls back to the built-in SQLite store otherwise -- no external
# service required. Without this, the factory's default "cli" runtime
# treats an unreachable/default PostgreSQL URL as fatal (by design, for
# a developer laptop expecting Postgres) rather than falling back, which
# is wrong for a container with no external services attached. This does
# not affect `tools/list` (registration never touches the store), only
# the tool call paths (remember/recall/etc.) -- see bare-container-contract
# root-cause report, fact #11.
ENV CORTEX_RUNTIME=cowork

# Health check: the process is alive and the full tool-registration import
# chain (mcp_server.__main__, all 49 standalone tool handlers) succeeds --
# NOT a database reachability probe. Registration must succeed with zero
# external services (see CORTEX_RUNTIME above); a DB-touching healthcheck
# would fail this image's own DB-less contract. Exit 0 means ready; any
# non-zero from entrypoint propagates.
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD python -c "import mcp_server.__main__"

# MCP servers typically run stdio transport; no ports to expose.
# Prometheus metrics endpoint is served by the sidecar in Phase 7.1.
#
# Use `python -m mcp_server` — the invocation documented in the package's
# __main__.py — so the image never depends on a console-script name
# (`hypermnesia-mcp` / `cortex-doctor`) staying stable across renames.
ENTRYPOINT ["python", "-m", "mcp_server"]
