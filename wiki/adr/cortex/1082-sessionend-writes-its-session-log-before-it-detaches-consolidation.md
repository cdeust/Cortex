---
created: 2026-09-17T13:57:27Z
kind: adr
number: 1082
status: accepted
tags: [hooks, session-log, codex, consolidation]
title: SessionEnd writes its session log before it detaches consolidation
---
# ADR-1082: SessionEnd writes its session log before it detaches consolidation

## Status

accepted

## Context

hooks/session_lifecycle.py wrote the session-log row, then called `asyncio.run(consolidate_handler(...))` in-process before returning, at a depth (`light`/`standard`/`full`) gated by the session's turn count. Under Claude Code, SessionEnd has no enforced timeout, so this cost nothing beyond the hook's own wall time. Codex gives SessionEnd a 1 s soft / 3 s hard timeout, well under a consolidation cycle's cost (decay, optionally compress and CLS replay over the whole store), so the same in-process call risks the hook being killed mid-cycle or past its budget on every session end.

A detached launcher for a consolidation cycle already exists, `hooks/consolidate_background.py`, spawned by SessionStart (`_spawn_consolidate_cycle`, `subprocess.Popen(..., start_new_session=True)`, not waited on) when a shared TTL stamp (`~/.claude/methodology/.last_consolidate`) is older than `CORTEX_CONSOLIDATE_TTL_HOURS`. Its cycle is fixed — decay + compress + cls + memify + wiki maintenance, toggled only by `--deep` — independent of any one session's turn count, and it writes that shared stamp on completion so the next SessionStart knows the periodic sweep is fresh.

## Decision

`hooks/session_lifecycle.py` keeps its session-log write exactly where it was, before consolidation, and replaces the in-process `asyncio.run(consolidate_handler(...))` call with `_spawn_consolidation`: a `subprocess.Popen(cmd, start_new_session=True, ...)`, not waited on, that re-invokes this same module with `--consolidate <mode>` — `mode` is `_consolidation_mode(turn_count)`, the same light/standard/full gate the in-process call used. `main()` checks for that flag before reading stdin and, when present, runs `_run_consolidation_cycle(mode)` instead of processing a SessionEnd event.

This does not reuse `consolidate_background.py`. That module's cycle is a different concern — a periodic, turn-count-independent sweep — and it writes a stamp SessionStart's TTL coordinator reads to decide whether that sweep is due. Routing a per-session turn-gated cycle through it would have to either drop the turn gating (running the fixed heavy cycle on every session end) or, if it kept writing that stamp, let one session's light cycle silently suppress the next periodic full cycle for up to the TTL. Re-invoking `session_lifecycle.py` itself keeps the two cycles' semantics apart while still moving the slow part out of the hook's own process.

## Consequences

Easier: a Codex SessionEnd returns as soon as the log row and profile update are done, regardless of how long a consolidation cycle takes; the log row exists even if the spawn itself fails (`tests_py/hooks/test_session_lifecycle.py::TestSpawnConsolidation`::`test_the_session_log_row_exists_even_when_the_launcher_fails` pins the order by patching the launcher to raise). Under Claude Code, behaviour is unchanged in substance: consolidation still runs at the same gated depth, now out-of-process instead of in-process; `TestSpawnConsolidation::test_the_launcher_gets_the_same_mode_the_turn_count_earns` pins that the spawned command carries the same mode the old in-process call computed.

Harder: a consolidation failure is no longer visible to whatever reads the SessionEnd hook's own stderr in real time — it lands in `consolidate.log` instead, one process removed. Two detached consolidation launchers now exist for two different triggers (SessionStart's periodic sweep, SessionEnd's per-session cycle); a future reader has to know which one a given `consolidate.log` line came from by its mode name (`light`/`standard`/`full` vs `--deep`/non-`--deep`), since both write to the same log path.
