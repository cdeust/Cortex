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

FROM python:3.12-slim-bookworm AS builder

# Node.js 22 LTS
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Claude Code CLI
RUN npm install -g @anthropic-ai/claude-code

# PyTorch CPU-only (saves ~1.5GB vs full CUDA)
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

# Cortex — copy full source for editable install
COPY . /opt/cortex
RUN pip install --no-cache-dir -e "/opt/cortex[postgresql,codebase]" \
    && pip install --no-cache-dir sentence-transformers flashrank

# Pre-cache embedding model
RUN python3 -c "from sentence_transformers import SentenceTransformer; \
    SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')"

# ── Runtime ───────────────────────────────────────────────────────────────

FROM python:3.12-slim-bookworm

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

# Copy Node.js + Claude CLI from builder
COPY --from=builder /usr/bin/node /usr/bin/node
COPY --from=builder /usr/lib/node_modules /usr/lib/node_modules
COPY --from=builder /usr/bin/claude /usr/bin/claude
RUN ln -sf /usr/bin/node /usr/bin/nodejs

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

# Copy Python packages + cached models from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
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
    && echo "host all all 0.0.0.0/0 trust" >> /var/lib/postgresql/17/data/pg_hba.conf \
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
ENV PYTHONPATH=/opt/cortex

ENTRYPOINT ["/entrypoint.sh"]
