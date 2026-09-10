# ADR-0065: benchmarks/lib/bench_container.sh implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `benchmarks/lib/bench_container.sh`; original SHA-256 `edad26e1d9ffd8691760da03c913e6ee0e1ce7a924cec901b9d28860fe736c6f`.

## Original shell-comment, lines 2–12

````text
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

````

## Original shell-comment, lines 14–22

````text
# Best-effort sweep of orphaned `cortex-bench-pg-*` containers whose owning
# PID is dead — same pattern as tests_py/conftest.py::_drop_dead_orphaned_databases.
# A run killed by SIGKILL (OOM, `docker kill` on the wrong target, machine
# sleep) never reaches the teardown EXIT trap, so its container leaks; this
# reclaims it on the NEXT run instead of requiring manual `docker rm`.
# Non-fatal and conservative: a name that doesn't parse as <pid>-<hex>, or a
# PID that's still alive (even if reused by an unrelated process — the
# window is the container's own lifetime, seconds to low hours, so PID reuse
# racing this exact check is not a realistic concern here), is left alone.

````

## Original shell-comment, lines 51–72

````text
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

````

## Original shell-comment, lines 82–82

````text
        # Fail loudly rather than loop forever if the container died on startup.

````

## Original shell-comment, lines 102–103

````text
        # Kernel-assigned free port — the default, and the fix for the
        # cross-worktree contamination reproduce.sh's header documents.

````

## Original shell-comment, lines 107–112

````text
    # --shm-size=1g: Docker's default 64MB /dev/shm starves PostgreSQL's
    # parallel HNSW index builds (each parallel worker needs shared
    # memory for its build buffer); source: pgvector README §"Indexing",
    # https://github.com/pgvector/pgvector (L.1176 as of the vendored
    # copy consulted 2026-07-11) — required to avoid the REINDEX
    # DiskFull failure mode observed the night of 2026-07-10/11.

````

## Original shell-comment, lines 135–137

````text
        # -v: also remove the anonymous PGDATA volume — without it every run
        # leaks one volume (measured 2026-07-11: 46 orphans / 31.5 GB filled
        # the Docker VM until postgres could no longer init a datadir).

````


## Final non-Python residual audit

### benchmarks/lib/bench_container.sh — pre-cleanup line 23

````text
# Discover the kernel-assigned host port docker bound for the container's
# 5432/tcp. `docker port` output is "0.0.0.0:PORT" (one line per binding);
# take the numeric suffix of the last line. Preferred over scanning for a
# free port ourselves: asking the kernel for port 0 and reading back what it
# bound is atomic — a manual scan-then-bind has a TOCTOU race another
# process (or another concurrent reproduce.sh run) can win in between.
````

### benchmarks/lib/bench_container.sh — pre-cleanup line 57

````text
        # Explicit override: caller takes responsibility for the port being
        # free and for any cross-run collision it may cause (mirrors
        # conftest.py's CORTEX_TEST_DATABASE_URL override — respected verbatim).
````
