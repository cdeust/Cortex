# Codex native integration verification, 4.23.2

Verified on 2026-09-22 with Codex 0.154.0 on macOS arm64. Native tests used
explicit SQLite scratch storage, an isolated Cortex configuration root and
reviewed hook hashes. No test memory was written to the production store.

## Observed native behavior

- The child developer context contained both the seeded team decision and the
  seeded role prior. The child returned both markers. Its task was opaque to
  hooks, and the briefing correctly identified itself as role/project context.
- A native `cat cue-file.txt` call raised its project memory's heat from 0.3
  to 0.4. A memory mentioning the same file in a sibling project stayed at 0.3.
- Native SessionEnd produced one session-log entry and one completion receipt.
  No queue job remained pending after the worker completed.
- The pinned wheel initialized, listed 59 tools, and answered `memory_stats`
  through the stdio verifier in 112.58 seconds with a clean candidate cache.

The native parent thread was `01a0ca1d-5135-7932-9c4c-ed1886e6fc7e`; the child
was `01a0ca1d-e9e4-78a1-8056-89f7c8b107a8`. The test used the packaged commands
from the manifest for the affected hooks and SessionStart. Unrelated capture,
auto-recall and edit hooks were omitted to isolate the observed heat change.

## Regression and interruption evidence

The combined affected suite passed 279 tests with no skips or warnings, using a
dedicated PostgreSQL test database plus isolated SQLite fixtures. Both backends
passed the 79-test priming suite. Six priming mutations and four lifecycle
mutations were detected by ordinary test failures.

Queue tests interrupt a worker using synchronization primitives, replay after
partial log/profile effects, exercise concurrent workers, preserve the original
working directory and storage selection, and retain failed jobs. Measured intake
was 64–65 ms in three local observations, including a queued event whose package
resolver could not run. These timings are observations, not a guarantee against
an arbitrarily stalled filesystem. Windows crash durability was not measured.

## Reproduction

Run the affected tests named in ADR-1084, ADR-1085 and ADR-1086 with an explicitly
selected disposable backend. Build the wheel with `uv build --wheel`, supply it
through `UV_FIND_LINKS`, and run `scripts/verify_mcp_hosts.py` with
`--storage-selection sqlite --clients codex-cli --profiles full` and the pinned
manifest command. Keep the verifier's full-surface check enabled.

For native acceptance, seed a role prior, a project team decision, a file cue and
a sibling-project control in disposable storage. Start a Codex session with the
candidate hook definitions and their reviewed hashes, spawn a child without
parent-history inheritance, read the cue file, then inspect the child developer
context, database heat, session log and queue receipt. Backend selection must be
explicit in hooks and in any MCP server used by the test.

## Published-artifact follow-up

The published wheel matched all 659 runtime Python files at release commit
`c8827be`. A subsequent native run under a macOS `/var/folders` project alias
confirmed briefing delivery and durable SessionEnd, but its file-cue memory
remained at 0.3. Priming resolved the query project to `/private/var/folders`
while the explicitly attached memory retained `/var/folders`. Issue #629 records
this mismatch; 4.23.3 preserves the stored project identity for scope queries and
canonicalizes only cooldown keys. Three focused regressions fail on 4.23.2 and
pass with that correction on both PostgreSQL and SQLite.
