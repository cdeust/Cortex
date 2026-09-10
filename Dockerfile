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
# source: ADR-0812





#
# source: ADR-0812

# source: ADR-0812






FROM python:3.14-slim@sha256:cea0e6040540fb2b965b6e7fb5ffa00871e632eef63719f0ea54bca189ce14a6 AS builder

WORKDIR /build

# Build deps only — stripped from the runtime image.
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# source: ADR-0812









RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY pyproject.toml README.md ./
COPY mcp_server ./mcp_server
COPY tests_py ./tests_py

# source: ADR-0812



#
# source: ADR-0812






#
# source: ADR-0812








COPY requirements/runtime-postgresql.txt requirements/packaging.txt /tmp/
RUN pip install --no-cache-dir --no-deps --require-hashes -r /tmp/runtime-postgresql.txt

# The project itself, as a built wheel installed with --no-deps.
#
# source: ADR-0812




#
# source: ADR-0812

RUN pip install --no-cache-dir --no-deps --require-hashes -r /tmp/packaging.txt && \
    python -m build --wheel --no-isolation --outdir /tmp/dist . && \
    pip install --no-cache-dir --no-deps /tmp/dist/*.whl

# ── Runtime stage ────────────────────────────────────────────────────────

FROM python:3.14-slim@sha256:cea0e6040540fb2b965b6e7fb5ffa00871e632eef63719f0ea54bca189ce14a6

LABEL org.opencontainers.image.source="https://github.com/cdeust/Cortex"
LABEL org.opencontainers.image.description="Cortex — neuroscience-backed memory system for Claude Code (MCP)"
LABEL org.opencontainers.image.licenses="MIT"

# libpq5 is the runtime side of libpq-dev — psycopg[binary] uses it.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 cortex

# source: ADR-0812



COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

USER cortex
WORKDIR /home/cortex

# source: ADR-0812










ENV CORTEX_RUNTIME=cowork

# source: ADR-0812





HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD python -c "import mcp_server.__main__"

# Use stdio transport; no ports are exposed.
# source: ADR-0812
#
# source: ADR-0812


ENTRYPOINT ["python", "-m", "mcp_server"]
