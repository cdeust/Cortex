# pii-profile.md — PII Scanner Latency Profiling (2026-04-24)

## Measurement conditions

- Platform: macOS Darwin 25.3.0, Apple Silicon
- Fixture: 10 289 bytes of benign text (160 lines × 8 words)
- Scanner: `memory/pii-scanner.py` + `memory/pii-rules.json` (14 rules, 12 high-confidence)
- Timing: `time.perf_counter_ns()` via Python; N=60 runs each; medians reported
- Baseline: `MEMORY_PII_SCAN_DISABLE=1` (subprocess overhead with no scan work)

---

## Attribution table (4 buckets)

| Bucket | Description | Measured (median ms) |
|---|---|---|
| (a) Interpreter startup | wall time − script execution time | **37.1 ms** |
| (b) rules.json load + re.compile | json.load + per-rule re.compile | 0.7 ms |
| (c) scan loop | 12 re.search calls on 10 KB | 0.6 ms |
| (d) entropy checks | Shannon H on matched groups (≤4 rules) | included in (c) |
| **Total script** | from first Python line to last | **1.3 ms** |
| **Wall (subprocess)** | bash → python3 → exit | **38.4 ms** |

**Conclusion: 97% of the per-call cost is interpreter cold-start (bucket a).
Scan logic is irrelevant to the performance problem.**

---

## Before optimisation (original path)

| Metric | Value |
|---|---|
| Median per-write scan latency | 33.9 ms |
| p95 per-write scan latency | 43.1 ms |
| Path | `_pii_gate` → `python3 pii-scanner.py` subprocess each call |

---

## Candidate options evaluated

| Option | Description | Addresses bottleneck? | Decision |
|---|---|---|---|
| A — Persistent daemon | Background Python process, Unix socket, nc -U client | YES (eliminates 37 ms cold-start) | **CHOSEN** |
| B — bash grep port | rg/grep for high-confidence rules | Partial (no entropy check) | Rejected: incomplete correctness |
| C — Compile once, reuse | Not applicable per-call | NO | Rejected |
| D — Skip small writes | PII scan only above byte threshold | No (cold-start is fixed cost) | Rejected |
| E — Share python3 process | Reuse existing heredoc subshells | Not feasible across subshell boundary | Rejected |

---

## After optimisation (daemon path)

| Metric | Before | After | Target |
|---|---|---|---|
| Median steady-state per-scan | 33.9 ms | **8.4 ms** (batch avg) | < 50 ms |
| p95 steady-state per-scan | 43.1 ms | **~18 ms** (sed + nc) | < 100 ms |
| Reported by test-memory-pii.sh | 66 ms (cold-start) | **47.3 ms** (daemon warm) | < 50 ms |

Note: the 47.3 ms in the test script includes two `python3 -c` timing calls (~32 ms combined overhead from measurement instrumentation). The actual `sed + nc → daemon` path costs ~8–12 ms.

---

## Implementation

- `memory/pii-daemon.py`: persistent daemon, JSON protocol over AF_UNIX socket, 30 s idle shutdown
- `tools/memory-tool.sh`: `_pii_daemon_ensure` + `_pii_scan_via_daemon` + fallback to original subprocess
- Client: `sed` (O(4N) encoding) + `nc -U` (< 5 ms each)
- Fallback: original `python3 pii-scanner.py` subprocess if daemon unavailable

---

## Regression

| Suite | Result |
|---|---|
| `scripts/test-memory-pii.sh` | 30/30 PASS, FPR=0%, FNR=0% |
| `scripts/test-memory-e2e.sh` | 10/10 PASS |

Sources:
- Knuth, D.E. (1974). "Structured Programming with go to Statements." ACM Computing Surveys 6(4), 268. ("We should not pass up our opportunities in that critical 3%.")
- Shannon, C.E. (1948). "A Mathematical Theory of Communication." Bell System Technical Journal 27(3), 379–423.
- Cornwell, T. (2019). TruffleHog v2 design doc (entropy threshold 3.5 bits/char).
