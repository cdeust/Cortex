#!/usr/bin/env bash
# source: ADR-0065

# source: ADR-0065
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

# Read the host port from the final docker port binding.
# source: ADR-0065
discover_assigned_port() {
    docker port "$CONTAINER" 5432/tcp | tail -1 | awk -F: '{print $NF}'
}

# source: ADR-0065
wait_for_db() {
    echo "==> Waiting for PostgreSQL to accept a real connection from the host..."
    until DATABASE_URL="$BENCH_DB_URL" uv run --extra benchmarks python -c "
import os, sys, psycopg
try:
    psycopg.connect(os.environ['DATABASE_URL'], connect_timeout=2).close()
except Exception:
    sys.exit(1)
" >/dev/null 2>&1; do
        # source: ADR-0065
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
        # Use the explicit caller-supplied port override.
        # source: ADR-0065
        PG_PORT="$CORTEX_BENCH_PORT"
        publish="${PG_PORT}:5432"
    else
        # source: ADR-0065
        publish="0:5432"
    fi
    echo "==> Starting ephemeral PostgreSQL (${PG_IMAGE}), container '${CONTAINER}'..."
    # source: ADR-0065
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
        # source: ADR-0065
        docker rm -f -v "$CONTAINER" >/dev/null 2>&1 || true
    fi
}
