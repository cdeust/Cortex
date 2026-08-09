#!/usr/bin/env bash
# LongMemEval-only shortcut. This is a THIN WRAPPER around the single source of
# truth, benchmarks/reproduce.sh — it does not carry its own copy of the
# container / dataset / recall logic. Kept for the historical `make longmemeval`
# entry point; prefer `make reproduce` for the full pipeline.
#
# Delegates to: reproduce.sh --only longmemeval --no-ablation
# Extra args (e.g. --limit 10) pass through to the LongMemEval harness.
#
# Metric scope: session-level retrieval Recall@10 / MRR (NOT end-to-end QA
# accuracy). Comparable published baseline: LongMemEval paper (Wu et al.,
# ICLR 2025) Recall@10 78.4%.

set -euo pipefail
_HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "$_HERE/reproduce.sh" --only longmemeval --no-ablation "$@"

# ── everything below is unreachable (exec above) and retained only so the
# original standalone implementation stays in git history for reference. ──
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATASET_PATH="$REPO_ROOT/benchmarks/longmemeval/longmemeval_s.json"

# Official dataset location, per the LongMemEval authors' HF repository.
# source: https://huggingface.co/datasets/xiaowu0162/LongMemEval
DATASET_URL="https://huggingface.co/datasets/xiaowu0162/LongMemEval/resolve/main/longmemeval_s"
# source: measured 2026-07-03 against the HF copy (278,025,796 bytes),
# byte-identical to the file behind every published Cortex result.
DATASET_SHA256="08d8dad4be43ee2049a22ff5674eb86725d0ce5ff434cde2627e5e8e7e117894"

# pgvector's official image; any PostgreSQL >= 15 with the vector
# extension available works (mcp_server/infrastructure/pg_schema.py
# creates the extensions itself on first connect).
PG_IMAGE="pgvector/pgvector:pg16"
PG_PORT="${CORTEX_BENCH_PORT:-55432}"
CONTAINER="cortex-bench-pg"
BENCH_DB_URL="postgresql://postgres:cortex_bench@localhost:${PG_PORT}/cortex_bench"

started_container=0

need_cmd() {
    command -v "$1" >/dev/null 2>&1 || {
        echo "error: '$1' is required but not installed." >&2
        exit 1
    }
}

sha256_of() {
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1" | awk '{print $1}'
    else
        shasum -a 256 "$1" | awk '{print $1}'
    fi
}

fetch_dataset() {
    if [ -f "$DATASET_PATH" ]; then
        echo "==> Dataset present: $DATASET_PATH"
    else
        echo "==> Downloading LongMemEval-S (~265 MB) from the official HF repo..."
        curl -L --fail --progress-bar -o "$DATASET_PATH" "$DATASET_URL"
    fi
    echo "==> Verifying dataset checksum..."
    local actual
    actual="$(sha256_of "$DATASET_PATH")"
    if [ "$actual" != "$DATASET_SHA256" ]; then
        echo "error: dataset checksum mismatch." >&2
        echo "  expected: $DATASET_SHA256" >&2
        echo "  actual:   $actual" >&2
        echo "The upstream file changed or the download is corrupt." >&2
        echo "Delete $DATASET_PATH and retry; open an issue if it persists." >&2
        exit 1
    fi
    echo "==> Checksum OK."
}

start_db() {
    if docker ps --format '{{.Names}}' | grep -q "^${CONTAINER}$"; then
        echo "==> Reusing running container ${CONTAINER}."
        return
    fi
    docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
    echo "==> Starting ephemeral PostgreSQL (${PG_IMAGE}) on port ${PG_PORT}..."
    docker run -d --name "$CONTAINER" \
        -e POSTGRES_PASSWORD=cortex_bench \
        -e POSTGRES_DB=cortex_bench \
        -p "${PG_PORT}:5432" \
        "$PG_IMAGE" >/dev/null
    started_container=1
    echo "==> Waiting for PostgreSQL to accept a real connection from the host..."
    # Real host connection, not pg_isready — same defect and same reasoning as
    # reproduce.sh::start_db(); see the comment there for the entrypoint evidence,
    # the measured optimism of both pg_isready variants, and the 2026-08-09 sweep
    # failures the socket probe caused.
    until DATABASE_URL="$BENCH_DB_URL" uv run --extra benchmarks python -c "
import os, sys, psycopg
try:
    psycopg.connect(os.environ['DATABASE_URL'], connect_timeout=2).close()
except Exception:
    sys.exit(1)
" >/dev/null 2>&1; do
        if [ -z "$(docker ps -q --filter "name=^${CONTAINER}$")" ]; then
            echo "error: container ${CONTAINER} exited before PostgreSQL became ready." >&2
            docker logs --tail 30 "$CONTAINER" >&2 2>/dev/null || true
            exit 1
        fi
        sleep 1
    done
}

teardown() {
    if [ "$started_container" = "1" ] && [ "${KEEP_DB:-0}" != "1" ]; then
        echo "==> Removing ephemeral container ${CONTAINER} (KEEP_DB=1 to keep)."
        docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
    fi
}

main() {
    need_cmd docker
    need_cmd curl
    need_cmd uv
    if ! docker info >/dev/null 2>&1; then
        echo "error: the Docker daemon is not running." >&2
        echo "Start it (Docker Desktop, 'colima start', ...) and retry." >&2
        exit 1
    fi
    fetch_dataset
    start_db
    trap teardown EXIT
    echo "==> Running the benchmark through the production recall path..."
    echo "    (full 500-question run takes ~40 min; pass --limit N for less)"
    cd "$REPO_ROOT"
    DATABASE_URL="$BENCH_DB_URL" uv run --extra benchmarks python \
        benchmarks/longmemeval/run_benchmark.py "$@"
}

main "$@"
