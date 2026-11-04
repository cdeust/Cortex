---
created: 2026-11-04T14:00:00Z
kind: adr
number: 1118
status: accepted
tags: [groomer, coordinator, hooks, issue-683, amends-adr-0527, amends-adr-1097]
title: An unreadable groomer.pid or a coordinator bug starts no cycle
---
# ADR-1118: An unreadable groomer.pid or a coordinator bug starts no cycle

## Status

accepted. Amends ADR-0527 (the coordinator degrades to the legacy spawn when it is unavailable) and ADR-1097 point 5 (the legacy path remains for the coordinator failures ADR-1097 does not cover).

## Context

Issue #683: after ADR-1097, two failure paths of the groomer coordinator could still end in a consolidate cycle started outside the coordinator's lock, the duplicate-cycle race that ADR-0527 says #171 removed.

1. `GroomerCoordinator.is_groomer_running` caught `(OSError, ValueError)` and returned False. A missing or unparseable `groomer.pid` is correctly "not running", but every other `OSError` (permission denied, I/O error) read as "not running" too, so the next SessionStart spawned a cycle although a live one may hold the file.
2. `_maybe_background_consolidate` caught `Exception` and called `_legacy_background_consolidate`, which bypasses the lock and the `groomer.pid` guard and writes a stamp, "<iso> (in-flight)", that `read_stamp` cannot parse. Any exception not handled earlier, including a bug in the coordinator, took this path. ADR-1097 point 5 gives I/O failures on the coordinator's own files as the case the legacy path remains for.

The owner's rule is root cause or hard failure, no silent fallback.

## Decision

1. `is_groomer_running` returns False only for a missing `groomer.pid` (`FileNotFoundError`) or an unparseable one (`ValueError`, which includes bytes that do not decode as UTF-8). Any other `OSError` raises `GroomerPidUnreadableError`, a `RuntimeError` so that it cannot reach the `OSError` degrade path.
2. At SessionStart, `GroomerPidUnreadableError` is handled like `LivenessProbeUnavailableError` (ADR-1097 point 3): the window is deregistered, the cause is logged at ERROR, and no stamp, no `groomer.pid` and no cycle are written or started.
3. `_maybe_background_consolidate` sends only `OSError` to the legacy spawn, the case ADR-1097 point 5 documents. Any other exception is logged at ERROR with its type and starts no cycle. The hook stays non-fatal.
4. A failed spawn inside `ensure_cycle` (`OSError` from the log file or `Popen`) is not an I/O failure on the coordinator's files: `_spawn_consolidate_cycle` logs it at ERROR and returns None, so it never leaves the lock as an `OSError` and never reaches the legacy spawn. The period stays stamped, so no other window retries before it elapses.
5. Not decided here: whether to remove the legacy spawn for `OSError` as well. It still bypasses the lock; that is the residual ADR-1097 point 5 left open.

## Consequences

Positive: neither an unreadable `groomer.pid` nor a coordinator bug can start a cycle outside the lock; both are visible in the hook log at ERROR with their cause.

Negative: while `groomer.pid` stays unreadable, or while the coordinator has a bug, no consolidation cycle starts until the condition is fixed. This is deliberate under the hard-failure rule. An `ImportError` of the coordinator module now also starts no cycle instead of the legacy one.

Tests: `tests_py/hooks/test_groomer_degrade_paths.py` (an EACCES read of `groomer.pid`, an unexpected coordinator exception and a failed `Popen` each start no cycle; an unusable coordinator directory still takes the legacy path).
