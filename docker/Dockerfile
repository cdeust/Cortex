# Cortex Runtime — Full memory system in a container
#
# Multi-stage build: Python 3.12 + PostgreSQL 17 + pgvector + Claude Code CLI
#
# Claude Code runs INSIDE the container with Cortex MCP pre-configured via
# stdio. No HTTP bridge needed — same architecture as ai-architect-feedback-loop.
#
# Usage:
#   docker build -t cortex-runtime -f docker/Dockerfile .
#   docker run -it \
#     -v /path/to/project:/workspace \
#     -v cortex-pgdata:/var/lib/postgresql/17/data \
#     -v ~/.claude:/home/cortex/.claude-host:ro \
#     -v ~/.claude.json:/home/cortex/.claude-host-json/.claude.json:ro \
#     cortex-runtime
#
# The cortex-pgdata volume persists memories across container restarts.

# ── Builder ───────────────────────────────────────────────────────────────

# Base image pinned by digest so a rebuild cannot silently pick up a
# different python:3.12-slim-bookworm. Digest resolved from the multi-arch manifest
# list, so it stays correct on both amd64 and arm64.
#   source: registry-1.docker.io/v2/library/python/manifests/3.12-slim-bookworm,
#           docker-content-digest header, fetched 2026-07-27.
# Refresh: Dependabot's `docker` ecosystem (.github/dependabot.yml) opens a
# PR when the tag moves; do not hand-edit without re-fetching the header.
FROM python:3.14-slim-bookworm@sha256:86f975aca15cf04a40b399eebede9aea7c82eae084d1f1a0a6ef6bcaae871a30 AS builder

# Node.js 22 LTS.
#
# This used to be `curl -fsSL https://deb.nodesource.com/setup_22.x | bash -`,
# which executes an unreviewed remote script as root at build time — whatever
# that URL serves, whenever it is fetched. It is the single largest piece of
# trust this image extended to a third party, and it cannot be pinned: there
# is no hash to check a pipe against. (OpenSSF Scorecard reports it as
# `downloadThenRun not pinned by hash`.)
#
# Replaced by what the script itself does, spelled out: fetch the signing
# key, register the signed apt source, install the signed package. curl now
# feeds `gpg --dearmor`, which is not an interpreter — nothing is executed.
# apt then verifies the package signature against that key.
#
# source: https://github.com/nodesource/distributions#installation-instructions
#         (the manual instructions the setup script automates)
ARG NODE_MAJOR=22
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl gnupg \
    && install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
       | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
    && chmod a+r /etc/apt/keyrings/nodesource.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_${NODE_MAJOR}.x nodistro main" \
       > /etc/apt/sources.list.d/nodesource.list \
    && apt-get update && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Claude Code CLI, installed with `npm ci` against a committed lockfile
# instead of `npm install -g @anthropic-ai/claude-code`.
#
# The old form was unversioned, so the image tracked whatever the registry
# served that minute — no way to reproduce a build, and no integrity check.
# `npm ci` is also the only install form Scorecard accepts as pinned (the
# other being a git URL at a commit SHA); an exact version on the command
# line is NOT enough. The lockfile additionally records a sha512 integrity
# hash for every transitive package, which npm verifies on extract.
#
# Bumping the CLI is `npm install --package-lock-only` in that directory,
# which is a reviewable diff rather than a silent change of image contents.
COPY docker/claude-code/package.json docker/claude-code/package-lock.json /opt/claude-code/
RUN cd /opt/claude-code && npm ci --omit=dev --ignore-scripts

# Python dependencies, hash-pinned. Every requirement in this file carries a
# hash from uv.lock (scripts/generate_pip_constraints.py), including the
# CPU-only torch build that keeps ~2GB of nvidia-cu13-* wheels out of the
# image — that used to be a bare `--index-url` flag whose artifact no
# lockfile described. `--require-hashes` makes pip refuse anything whose
# bytes do not match.
#
# Installed into a virtualenv at a version-free path so the runtime stage
# copies one directory and no COPY names the Python version. See the root
# Dockerfile for the incident that rule comes from: a literal
# .../python3.13/site-packages path broke on every base-image bump.
# --no-deps: the file is the complete, uv-resolved dependency graph — pip
# must install it as-is rather than re-deriving it from metadata, which
# breaks the moment pyproject.toml's [tool.uv] override-dependencies
# steers a package past a bound another package's metadata still declares
# (issue: PR #332, mpmath 1.4.1 vs sympy's `mpmath<1.4`).
COPY requirements/docker-runtime.txt /tmp/requirements.txt
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --no-cache-dir --no-deps --require-hashes -r /tmp/requirements.txt

# Cortex itself: --no-deps because every dependency was just installed from
# the hashed file above, and re-resolving here would reintroduce unpinned
# installs. An editable install of a local path with --no-deps is the form
# Scorecard recognises as pinned.
COPY . /opt/cortex
RUN pip install --no-cache-dir --no-deps -e /opt/cortex

# Pre-cache embedding model. Retry-with-backoff, fail-loudly: same shape and
# same attempt/backoff constants as ci.yml's "Pre-download embedding model"
# step, for the same reason — a transient huggingface.co blip must not decide
# whether the image builds. The bare single-shot form failed this build on PR
# #337 (CI run 30749502167, 2026-08-02) with "We couldn't connect to
# 'https://huggingface.co'" after 73s, on a commit touching neither this file
# nor anything it depends on; the same job had passed on its parent commit.
# No BuildKit cache mount here on purpose: the runtime stage COPYs this cache
# out of the builder layer, and a cache mount is not part of the layer.
# source: .github/workflows/ci.yml:131-139 (5 attempts, attempt*10s backoff)
RUN for attempt in 1 2 3 4 5; do \
        python3 -c "from sentence_transformers import SentenceTransformer; \
            SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')" && exit 0; \
        echo "HF pre-download attempt ${attempt} failed; retrying in $((attempt * 10))s" >&2; \
        sleep $((attempt * 10)); \
    done; \
    echo "HF pre-download failed after 5 attempts" >&2; \
    exit 1

# ── Runtime ───────────────────────────────────────────────────────────────

FROM python:3.14-slim-bookworm@sha256:86f975aca15cf04a40b399eebede9aea7c82eae084d1f1a0a6ef6bcaae871a30

# System: PostgreSQL 17 + pgvector + git + ripgrep
RUN apt-get update && apt-get install -y --no-install-recommends \
        gnupg2 lsb-release curl ca-certificates git ripgrep gosu \
    && echo "deb http://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" \
       > /etc/apt/sources.list.d/pgdg.list \
    && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
       | gpg --dearmor -o /etc/apt/trusted.gpg.d/postgresql.gpg \
    && apt-get update && apt-get install -y --no-install-recommends \
       postgresql-17 postgresql-17-pgvector \
    && rm -rf /var/lib/apt/lists/*

# Copy Node.js + Claude CLI from builder. The CLI now lives in the project
# directory `npm ci` installed it into, not in the global prefix.
COPY --from=builder /usr/bin/node /usr/bin/node
COPY --from=builder /opt/claude-code /opt/claude-code
RUN ln -sf /usr/bin/node /usr/bin/nodejs \
    && ln -sf /opt/claude-code/node_modules/.bin/claude /usr/bin/claude

# ripgrep vendor symlink for Claude Code
RUN ARCH=$(dpkg --print-architecture) && \
    ARCH_MAP="amd64:x64-linux arm64:arm64-linux" && \
    for pair in $ARCH_MAP; do \
        if [ "${pair%%:*}" = "$ARCH" ]; then \
            RG_DIR="/usr/bin/vendor/ripgrep/${pair##*:}"; \
            mkdir -p "$RG_DIR"; \
            ln -sf /usr/bin/rg "$RG_DIR/rg"; \
        fi; \
    done

# Copy Python packages + cached models from builder.
#
# This was `COPY --from=builder /usr/local/lib/python3.12/site-packages ...`
# against a python:3.14 base — a path that has not existed in either stage
# since the base image moved off 3.12, so this image could not build at all.
# It went unnoticed because nothing in CI builds this Dockerfile; the job
# added in .github/workflows/ci.yml alongside this change is what makes the
# next such breakage visible. The venv path carries no version, so a future
# base bump cannot reintroduce the same class of failure.
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY --from=builder /root/.cache/huggingface /home/cortex/.cache/huggingface

# Non-root user
RUN useradd -m -u 1000 -s /bin/bash cortex \
    && mkdir -p /workspace /opt/cortex \
    && chown -R cortex:cortex /workspace /opt/cortex

# PostgreSQL directories
RUN mkdir -p /run/postgresql /var/log/postgresql \
    && chown -R postgres:postgres /run/postgresql /var/log/postgresql /var/lib/postgresql

# Initialize PostgreSQL cluster
USER postgres
RUN rm -rf /var/lib/postgresql/17/data \
    && /usr/lib/postgresql/17/bin/initdb -D /var/lib/postgresql/17/data \
    && echo "host all all 127.0.0.1/32 scram-sha-256" >> /var/lib/postgresql/17/data/pg_hba.conf \
    && echo "listen_addresses = 'localhost'" >> /var/lib/postgresql/17/data/postgresql.conf
USER root

# Copy Cortex source
COPY --chown=cortex:cortex . /opt/cortex

# Fix ownership of cached models
RUN chown -R cortex:cortex /home/cortex/.cache 2>/dev/null || true

# Entrypoint
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

VOLUME /workspace
VOLUME /var/lib/postgresql/17/data
WORKDIR /workspace

ENV DATABASE_URL=postgresql://cortex:cortex@localhost:5432/cortex
ENV CORTEX_MEMORY_STORE_BACKEND=postgresql
ENV CORTEX_RUNTIME=cli
ENV PYTHONPATH=/opt/cortex

ENTRYPOINT ["/entrypoint.sh"]
