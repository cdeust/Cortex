# PostgreSQL readiness probe — why the benchmark harness must connect for real

**Date:** 2026-08-09
**Trigger:** 3 of the 5 cells of the issue #368 trust-factor sweep died in ~3s
each with `psycopg.OperationalError: connection refused`, while the same code
had just completed a 1h21 cell successfully.
**Outcome:** `benchmarks/reproduce.sh::start_db()` and
`benchmarks/repro_longmemeval.sh::start_db()` now wait on a real `psycopg`
connection from the host instead of `pg_isready`.

---

## 1. Symptom

`benchmarks/results/trust-factor-sweep/20260809T063306Z/`:

| cell | duration | outcome |
|---|---|---|
| W=1.0 | 1h21 | completed |
| W=0.8 | 3s | `connection refused`, port 32771 |
| W=0.7 | 3s | `connection refused`, port 32772 |
| W=0.6 | 3s | `connection refused`, port 32773 |
| W=0.5 | — | killed while running (see §5) |

The three failures are identical: the ephemeral container starts, `start_db()`
returns, and the benchmark's first connection from the host is refused. Failure
is loud (`rc=1`), never silent — no cell produced wrong numbers, only no numbers.

## 2. Mechanism

`start_db()` waited on:

```bash
until docker exec "$CONTAINER" pg_isready -U postgres -d cortex_bench; do sleep 1; done
```

Without `-h`, `pg_isready` uses the container's **Unix socket**. The postgres
entrypoint runs `initdb` against a temporary server that listens on that socket
and nowhere else — its own source, `/usr/local/bin/docker-entrypoint.sh`:

```
# start socket-only postgresql server for setting up or running scripts
docker_temp_server_start() {
    # does not listen on external TCP/IP and waits until start finishes
    set -- "$@" -c listen_addresses='' -p "${PGPORT:-5432}"      # line 297
}
docker_temp_server_stop() {
    pg_ctl -D "$PGDATA" -m fast -w stop                          # line 311
}
```

So the socket answers "ready" **during initialization**, the loop exits, and the
host's TCP connection hits a server that is not listening yet (or is being
restarted). The race is timing-dependent, which is why one cell survived and
three enchained cells — starting 3s apart, while the previous container was
still tearing down — did not.

## 3. Measurement

Two candidate probes were compared against the thing that actually matters: a
`psycopg` connection from the host, over the published port, with the same URL
the benchmarks use.

**Protocol.** 5 fresh containers. For each, three probes loop in **independent
processes** against the same container and each records its own first success,
so no probe waits on another.

**Environment.** macOS 26.6, Docker 28.3.3, `pgvector/pgvector:pg16`,
`-p 0:5432 --shm-size=1g`. Harness:
`scratchpad/probe_race2.sh` (reproduced verbatim in §6).

| rep | unix socket | container TCP | real host connection | socket early by | TCP early by |
|---|---|---|---|---|---|
| 1 | 0.29s | 0.62s | 1.60s | 1.31s | 0.98s |
| 2 | 0.28s | 0.59s | 2.62s | 2.34s | 2.03s |
| 3 | 0.28s | 0.59s | 2.78s | 2.50s | 2.19s |
| 4 | 0.28s | 0.60s | 2.67s | 2.39s | 2.07s |
| 5 | 0.29s | 0.59s | 2.65s | 2.36s | 2.06s |

- `pg_isready` over the unix socket: optimistic in **5/5** reps, median **2.36s**
  (range 1.31–2.50s).
- `pg_isready` over TCP inside the container: optimistic in **5/5** reps, median
  **2.06s** (range 0.98–2.19s).

**Conclusion.** Both `pg_isready` variants declare readiness while a real
connection is still refused. Only the real connection is a valid probe. Note the
container-TCP probe was the *first* fix attempted and the measurement rejected
it — the socket-only entrypoint evidence of §2 explains why the socket probe is
wrong, but it does not license any cheaper substitute.

## 4. Two harness errors made while measuring

Both are recorded because each would have produced a confident wrong answer.

**(a) Ordering bias.** The first harness probed OLD, then NEW, then REAL
sequentially inside one loop, so REAL was always measured last and looked late by
roughly the cost of the two probes preceding it (~0.4s). It reported "TCP probe
optimistic by 0.44s" — a number manufactured by the measurement, not observed in
the system. Fixed by giving each probe its own process (§3). This is the same
trap as the 4253160 lesson: comparing values captured at different instants.

**(b) Locale-truncated arithmetic.** The summary `awk` parsed `"2.78"+0` as `2`
under `fr_FR` (comma decimal separator), so every reported magnitude was wrong
("worst by 2,00s" for a true 2.50s gap). The pass/fail verdict survived by
accident, the numbers did not. All figures in §3 are recomputed in Python from
the raw per-rep output.

## 5. Data invalidated

The whole sweep is discarded, not just the three crashed cells. A grid whose
cells were produced under a harness carrying a known defect has no single
provenance, so **all five cells must be re-run on the corrected harness** —
including W=1.0, which completed, and W=0.5, which was killed mid-run once its
result was known to be unusable. The pre-registered decision rule in
`docs/provenance/trust-factor-calibration.md` requires the complete grid; it is
not applied to a partial one.

## 6. Reproducing

```bash
scratchpad/probe_race2.sh 5     # 5 fresh containers, 3 racing probes each
```

The harness is intentionally kept out of the repo: it asserts nothing about
Cortex, only about the postgres image's startup behaviour on this machine. Its
verbatim content and raw output are archived with this document's commit message.
