# Cortex Runtime — Full memory system in a container
#
# Multi-stage build: Python 3.12 + PostgreSQL 17 + pgvector + Claude Code CLI
#
# Run Claude Code inside the container with Cortex MCP configured over stdio.
# source: ADR-0872
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

# source: ADR-0872






FROM python:3.14-slim-bookworm@sha256:82bc3c539b8813ada9d68c63b40158fa002f7f33de9bf3312a3dfdc0620dff56 AS builder

# Node.js 22 LTS.
#
# source: ADR-0872





#
# Fetch the signing key, register the signed apt source, and install the verified package.
# source: ADR-0872
#
# source: ADR-0872

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

# source: ADR-0872

#
# source: ADR-0872





#
# source: ADR-0872

COPY docker/claude-code/package.json docker/claude-code/package-lock.json /opt/claude-code/
RUN cd /opt/claude-code && npm ci --omit=dev --ignore-scripts

# Install uv.lock's postgresql + codebase + container set into a venv at a
# version-free path, every artifact checked against the lock's sha256.
# source: ADR-0872
# source: ADR-1092
COPY --from=ghcr.io/astral-sh/uv:0.11.3@sha256:90bbb3c16635e9627f49eec6539f956d70746c409209041800a0280b93152823 /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock /tmp/cortex-lock/
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN cd /tmp/cortex-lock && UV_PROJECT_ENVIRONMENT=/opt/venv uv sync --locked \
    --inexact --no-cache --no-install-project --no-default-groups \
    --extra postgresql --extra codebase --group container

# source: ADR-0872



COPY . /opt/cortex
RUN pip install --no-cache-dir --no-deps -e /opt/cortex

# source: ADR-0872









RUN for attempt in 1 2 3 4 5; do \
        python3 -c "from sentence_transformers import SentenceTransformer; \
            SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')" && exit 0; \
        echo "HF pre-download attempt ${attempt} failed; retrying in $((attempt * 10))s" >&2; \
        sleep $((attempt * 10)); \
    done; \
    echo "HF pre-download failed after 5 attempts" >&2; \
    exit 1

# ── Runtime ───────────────────────────────────────────────────────────────

FROM python:3.14-slim-bookworm@sha256:82bc3c539b8813ada9d68c63b40158fa002f7f33de9bf3312a3dfdc0620dff56

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

# Copy Node.js and the project-local Claude CLI from the builder.
# source: ADR-0872
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
# source: ADR-0872






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

# source: ADR-0872
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
