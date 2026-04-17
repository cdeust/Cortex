# Cortex MCP server — production image.
#
# Build:    docker build -t cortex:latest .
# Run:      docker run --rm \
#             -e DATABASE_URL=postgresql://user:pass@host:5432/cortex \
#             -e CORTEX_MEMORY_POOL_INTERACTIVE_MAX=16 \
#             cortex:latest
#
# Requires: PostgreSQL 15+ with pgvector + pg_trgm extensions on the
# DATABASE_URL endpoint. The image does NOT bundle PostgreSQL; it
# connects to an external instance.
#
# Source: docs/program/phase-5-pool-admission-design.md §7.

FROM python:3.13-slim AS builder

WORKDIR /build

# Build deps only — stripped from the runtime image.
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY mcp_server ./mcp_server
COPY tests_py ./tests_py

RUN pip install --no-cache-dir --upgrade pip build && \
    pip install --no-cache-dir .[postgresql]

# ── Runtime stage ────────────────────────────────────────────────────────

FROM python:3.13-slim

LABEL org.opencontainers.image.source="https://github.com/cdeust/Cortex"
LABEL org.opencontainers.image.description="Cortex — neuroscience-backed memory system for Claude Code (MCP)"
LABEL org.opencontainers.image.licenses="MIT"

# libpq5 is the runtime side of libpq-dev — psycopg[binary] uses it.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 cortex

COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

USER cortex
WORKDIR /home/cortex

# Health check: probe the settings module loads + DB URL is reachable.
# Exit 0 means ready; any non-zero from entrypoint propagates.
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD python -c "from mcp_server.infrastructure.memory_config import get_memory_settings; get_memory_settings()"

# MCP servers typically run stdio transport; no ports to expose.
# Prometheus metrics endpoint is served by the sidecar in Phase 7.1.
ENTRYPOINT ["neuro-cortex-memory"]
