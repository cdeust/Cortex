#!/usr/bin/env bash
# Ephemeral PostgreSQL container lifecycle for the benchmark harnesses.
#
# Sourced by benchmarks/reproduce.sh. Extracted from it (behaviour unchanged,
# except start_db()'s wait split out into wait_for_db()) to keep that driver
# within the size limits of coding-standards.md §4.
#
# Contract with the caller — these globals must be set before sourcing:
#   PG_IMAGE, CONTAINER            (read)
#   PG_PORT, BENCH_DB_URL          (assigned by start_db)
#   started_container              (assigned by start_db)
# Optional: CORTEX_BENCH_PORT to pin the published port.

# Best-effort sweep of orphaned `cortex-bench-pg-*` containers whose owning
# PID is dead — same pattern as tests_py/conftest.py::_drop_dead_orphaned_databases.
# A run killed by SIGKILL (OOM, `docker kill` on the wrong target, machine
# sleep) never reaches the teardown EXIT trap, so its container leaks; this
# reclaims it on the NEXT run instead of requiring manual `docker rm`.
# Non-fatal and conservative: a name that doesn't parse as <pid>-<hex>, or a
# PID that's still alive (even if reused by an unrelated process — the
# window is the container's own lifetime, seconds to low hours, so PID reuse
# racing this exact check is not a realistic concern here), is left alone.
sweep_orphaned_containers() {
    local names name rest pid
    names="$(docker ps -a --format '{{.Names}}' | grep '^cortex-bench-pg-' || true)"
    [ -z "$names" ] && return
    while IFS= read -r name; do
        rest="${name#cortex-bench-pg-}"
        pid="${rest%%-*}"
        case "$pid" in
            ''|*[!0-9]*) continue ;;  # doesn't parse as <pid>-<hex> — leave it
        esac
        if kill -0 "$pid" 2>/dev/null; then
            continue  # owning process still alive — not an orphan
        fi
        echo "==> Reclaiming orphaned container ${name} (owning pid ${pid} is dead)."
        docker rm -f -v "$name" >/dev/null 2>&1 || true
    done <<< "$names"
}

# Discover the kernel-assigned host port docker bound for the container's
# 5432/tcp. `docker port` output is "0.0.0.0:PORT" (one line per binding);
# take the numeric suffix of the last line. Preferred over scanning for a
# free port ourselves: asking the kernel for port 0 and reading back what it
# bound is atomic — a manual scan-then-bind has a TOCTOU race another
# process (or another concurrent reproduce.sh run) can win in between.
discover_assigned_port() {
    docker port "$CONTAINER" 5432/tcp | tail -1 | awk -F: '{print $NF}'
}

# Block until the database accepts the connection the benchmarks themselves
# make. The probe must BE that connection — a psycopg connect from the HOST
# over the published port. Both cheaper probes were measured and both report
# ready while a real connection is still refused:
#   pg_isready over the container's unix socket : optimistic 5/5 runs,
#                                                 median 2.36s (1.31-2.50s)
#   pg_isready over TCP inside the container    : optimistic 5/5 runs,
#                                                 median 2.06s (0.98-2.19s)
# The socket probe is optimistic because the postgres entrypoint runs initdb
# against a socket-only temporary server — docker-entrypoint.sh
# docker_temp_server_start(): "start socket-only postgresql server […] does not
# listen on external TCP/IP", `listen_addresses=''` — which it then stops
# (docker_temp_server_stop) before the real server starts.
# source: measured 2026-08-09 on this machine (Docker 28.3.3,
#   pgvector/pgvector:pg16), 5 fresh containers, the three probes racing in
#   independent processes so none waits on another: unix 0.28-0.29s,
#   container-TCP 0.59-0.62s, real host connection 1.60-2.78s. Harness, raw
#   output and the biased first attempt that had to be redone:
#   docs/provenance/pg-readiness-probe-2026-08-09.md
# Why it matters: under the socket probe, 3 of the 5 trust-factor sweep cells
# died in ~3s each with "connection refused" (ports 32771-32773) —
# benchmarks/results/trust-factor-sweep/20260809T063306Z/.
wait_for_db() {
    echo "==> Waiting for PostgreSQL to accept a real connection from the host..."
    until DATABASE_URL="$BENCH_DB_URL" uv run --extra benchmarks python -c "
import os, sys, psycopg
try:
    psycopg.connect(os.environ['DATABASE_URL'], connect_timeout=2).close()
except Exception:
    sys.exit(1)
" >/dev/null 2>&1; do
        # Fail loudly rather than loop forever if the container died on startup.
        if [ -z "$(docker ps -q --filter "name=^${CONTAINER}$")" ]; then
            echo "error: container ${CONTAINER} exited before PostgreSQL became ready." >&2
            docker logs --tail 30 "$CONTAINER" >&2 2>/dev/null || true
            exit 1
        fi
        sleep 1
    done
}

start_db() {
    sweep_orphaned_containers
    local publish
    if [ -n "${CORTEX_BENCH_PORT:-}" ]; then
        # Explicit override: caller takes responsibility for the port being
        # free and for any cross-run collision it may cause (mirrors
        # conftest.py's CORTEX_TEST_DATABASE_URL override — respected verbatim).
        PG_PORT="$CORTEX_BENCH_PORT"
        publish="${PG_PORT}:5432"
    else
        # Kernel-assigned free port — the default, and the fix for the
        # cross-worktree contamination reproduce.sh's header documents.
        publish="0:5432"
    fi
    echo "==> Starting ephemeral PostgreSQL (${PG_IMAGE}), container '${CONTAINER}'..."
    # --shm-size=1g: Docker's default 64MB /dev/shm starves PostgreSQL's
    # parallel HNSW index builds (each parallel worker needs shared
    # memory for its build buffer); source: pgvector README §"Indexing",
    # https://github.com/pgvector/pgvector (L.1176 as of the vendored
    # copy consulted 2026-07-11) — required to avoid the REINDEX
    # DiskFull failure mode observed the night of 2026-07-10/11.
    docker run -d --name "$CONTAINER" \
        -e POSTGRES_PASSWORD=cortex_bench \
        -e POSTGRES_DB=cortex_bench \
        -p "${publish}" \
        --shm-size=1g \
        "$PG_IMAGE" >/dev/null
    started_container=1
    if [ -z "${CORTEX_BENCH_PORT:-}" ]; then
        PG_PORT="$(discover_assigned_port)"
        if [ -z "$PG_PORT" ]; then
            echo "error: could not discover the port docker assigned to ${CONTAINER}." >&2
            exit 1
        fi
    fi
    BENCH_DB_URL="postgresql://postgres:cortex_bench@localhost:${PG_PORT}/cortex_bench"
    echo "==> Run container: ${CONTAINER}   port: ${PG_PORT}   (isolated per-run — see MANIFEST.json)"
    wait_for_db
}

remove_container() {
    if [ "$started_container" = "1" ] && [ "$KEEP_DB" != "1" ]; then
        echo "==> Removing ephemeral container ${CONTAINER} (--keep-db to keep)."
        # -v: also remove the anonymous PGDATA volume — without it every run
        # leaks one volume (measured 2026-07-11: 46 orphans / 31.5 GB filled
        # the Docker VM until postgres could no longer init a datadir).
        docker rm -f -v "$CONTAINER" >/dev/null 2>&1 || true
    fi
}
