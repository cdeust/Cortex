---
created: 2026-10-07T00:00:00Z
kind: adr
number: 1094
status: accepted
tags: [capture, windows, hooks, issue-659]
title: Spool captures for a detached drainer where the resident worker cannot run
---
# ADR-1094: Spool captures for a detached drainer where the resident worker cannot run

## Status

accepted

## Context

Issue #659: since 17370a61 every PostToolUse capture goes through a resident
worker that needs `AF_UNIX`, `fcntl`, `geteuid` and `Popen(pass_fds)`. CPython on
Windows has none of them, `capture_peer.supported()` raised, and the hook
reported `capture_skipped` for every event: 1,730 attempts, zero memories, with
no visible signal (reporter's `telemetry.jsonl`, Windows 11, 4.23.1).

The first fix (PR #663 at baa8ece9) stored in the hook process on such platforms.
Measured on 2026-10-07 (macOS, isolated SQLite store, warm): `handlers/remember.py`
imports `sentence_transformers` in 3.61 s (`torch` 0.72 s, weights 0.10 s, one
encode 0.01 s); the whole in-process capture took 4.4 s warm and 10.5 s cold. The
hook has `timeout: 10` (`.claude-plugin/plugin.json`), and the host aborts a hook
that exceeds it ("PostToolUse hook timed out (per-hook abort)", Claude Code
2.1.292). The resident worker (ADR-0486, ADR-0508) exists precisely to pay that
import once; the in-process path put it back on the synchronous path of every
event, so the capture would be killed at the limit instead of refused.

## Decision

Where `capture_peer.is_supported()` is false the hook does not load the handler.
It validates the payload (`validate_payload`), writes it unchanged and atomically
to `<CLAUDE_DIR>/.capture-worker/spool/` (`infrastructure/capture_spool.py`) and
starts `python -m mcp_server.hooks.capture_drain` without waiting. POSIX is
unchanged (the resident worker).

- The spawn options are a pure function, `capture_dispatch.popen_options(platform)`:
  Windows `creationflags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP`,
  `close_fds`, stdin to `DEVNULL`, stdout and stderr to an append-only
  `drain.err` (so a crash before the drainer's own rotating `drain.log` exists is
  not lost), the launcher's environment; no `pass_fds` and no `start_new_session`
  (CPython ignores it on Windows). Other platforms use `start_new_session`.
- The drainer takes a non-blocking kernel lock (`msvcrt.locking` `LK_NBLCK` /
  `flock` `LOCK_NB`; the pattern of the Codex SessionEnd queue, ADR-1084). A loser
  exits at once without importing the handler. The winner stores every pending
  file through the same `capture_store.store` the worker awaits, on one event loop
  (one model load per burst), then releases the lock and scans once more. A file
  written between its last scan and the release has a drainer that lost the lock
  and exited; the rescan stores it.
- Delivery is at-least-once: a file is deleted after `store` returned; a replay after
  a crash is absorbed by the write gate. A refused, unreadable or failing file is
  renamed `*.rejected` and reported through `report_failure("capture_skipped")`;
  nothing is swallowed.
- The directory is private under the configured Cortex root (mode 0700 where the
  platform has modes; on Windows it inherits the user-profile ACL).

## Rejected

- The PR as first written (store in the hook): 4.4 to 10.5 s against a 10 s budget.
- One process per event with no spool: N imports of `torch`.
- Algorithmic embedding re-embedded at `consolidate`: `sqlite_store_search.py`
  isolates embedding spaces and the write gate is blind to neural rows.
- `async: true` on the hook: every platform, still one `torch` import per event.
- Named pipe with a current-user DACL: a second transport, lease and spawn stack.
- Spool on every platform: it would change the POSIX capture path (ADR-0486,
  ADR-0508), outside this issue.

## Consequences

Positive: the hook returns in milliseconds on Windows (0.06 s measured for the hook
body on macOS with the Windows branch simulated); one model load serves a burst;
`ci.yml`'s Windows leg runs the capture test files, so `is_supported()` false
natively, the real `msvcrt` lock and the real detached spawn are exercised.

Negative: a capture is persisted after the hook returns, not before; a drainer
killed by the host's process-tree cleanup leaves the file for the next event's
drainer. `CREATE_BREAKAWAY_FROM_JOB` is not requested: it fails when the host's job
object forbids breakaway. Whether the host destroys the tree on abort is unobserved,
since the hook no longer approaches its limit. The reporter's check, a
`telemetry.jsonl` with `remember` samples and no `capture_skipped`, is the
signal that closes #659's capture part. `check_setup` answering `ready: true` while
capture is broken is a separate defect (#660).
