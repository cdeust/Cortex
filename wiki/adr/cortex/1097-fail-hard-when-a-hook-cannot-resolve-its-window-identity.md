---
created: 2026-10-09T08:22:40Z
kind: adr
number: 1097
status: accepted
tags: [groomer, coordinator, session-registry, windows, issue-666]
title: Fail hard when a hook cannot resolve its window identity
---
# ADR-1097: Fail hard when a hook cannot resolve its window identity

## Status

accepted

## Context

Issue #666: the groomer coordinator keyed its sessions by the pid of the hook process itself. A hook lives for milliseconds, so by the next liveness check no registered session looked alive and the coordinator's single-cycle guarantee (ADR-0527, which removed the duplicate-cycle race of #171) did not hold. The identity that lives as long as the window is the pid of the claude process, found by walking the ancestors (ADR-0597 keys one registry file per window by that pid).

ADR-0527 says the coordinator degrades to the legacy spawn (`_legacy_background_consolidate`) when it is unavailable. That path bypasses the coordinator's lock and the `groomer.pid` guard and writes a stamp, "<iso> (in-flight)", that `read_stamp` cannot parse, so a second window that starts while a cycle is in flight spawns a duplicate cycle. While the Windows ancestor walk returned None (issue #665) every SessionStart took that path, which made a documented degrade path the permanent Windows steady state. The owner rejects catch-and-degrade fixes: root cause or hard failure. PR #678 (ADR-1096) fixed the Windows walk, so "no claude ancestor" is now a genuinely abnormal condition, not a platform property.

## Decision

1. The coordinator is keyed by `window_pid()`, the pid of the nearest claude ancestor (`claude_ancestor_pid`). `window_pid()` raises `WindowIdentityUnavailableError` when there is no such ancestor and never substitutes any other pid, in particular not `os.getpid()` and not the parent pid.
2. At SessionStart an unresolved window identity is a hard failure of the coordinator step: `WindowIdentityUnavailableError` (no claude ancestor) and `OSError` (unreadable process table, ADR-1096 point 5) are logged at ERROR level with the cause, and the hook registers nothing, spawns nothing and writes no stamp and no `groomer.pid`. It does not fall back to `_legacy_background_consolidate`. This amends the ADR-0527 rule that the coordinator degrades to the legacy spawn when it is unavailable, for this cause.
3. The same holds when the process table cannot be read while the coordinator is deciding whether a registered session is alive (`pid_alive` raising OSError inside `ensure_cycle`): it is the same condition, handled the same way, with no legacy spawn.
4. SessionEnd keeps its non-fatal handling: it logs and stops nothing when the identity cannot be resolved, because a missing deregistration is recovered by the next liveness purge.
5. The legacy spawn path remains only for the coordinator failures this decision does not cover (for example I/O errors on the coordinator's files). Whether to remove it altogether is not decided here.
6. Not decided here: pid reuse after a crash can keep a dead window looking alive, since the coordinator has no start-time check; this is the existing model of ADR-0597.

## Consequences

Positive: a hook that cannot tell which window it belongs to no longer starts a cycle outside the lock, so overlapping windows cannot start duplicate consolidation cycles by this route; the failure is visible in the hook log with its cause instead of a silent change of path.

Negative: on a host where the ancestor walk cannot work (an unreadable process table, or a launch with no claude ancestor) no consolidation cycle starts in that session until the condition is fixed. This is deliberate under the hard-failure rule. Residual limits: the access to the process table is only as sound as ADR-1096, and pid reuse is unchanged.
