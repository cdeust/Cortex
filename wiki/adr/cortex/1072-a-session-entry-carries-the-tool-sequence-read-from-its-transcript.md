---
created: 2026-09-16T11:12:38Z
kind: adr
number: 1072
status: accepted
tags: [procedural-memory, hooks, session-log, issue-591]
title: A session entry carries the tool sequence read from its transcript
---
# ADR-1072: A session entry carries the tool sequence read from its transcript

## Status

accepted

## Context

Procedural learning had never produced a skill: `procedural_skills` held 0 rows in the maintainer's store on 2026-09-16, and `recall_skills` returned an empty list both cwd-scoped and unscoped, matching the same measurement taken on 2026-08-25.

The chain stopped at its first link. `hooks/session_lifecycle.py::_build_session_entry` wrote `"toolsUsed": event.get("tools_used") or []` and `"turnCount": event.get("turn_count", 0)`, but the SessionEnd payload carries `session_id`, `transcript_path` and `cwd`, not those two fields. Measured on the live `session-log.json`: 413 sessions, every one with `toolsUsed: []` and `turnCount: 0`. `procedural_skill_writer._session_log_to_mining_input` drops an entry with no tools, so `maybe_mine_skills` always returned `skipped / insufficient_history` (issue #591).

The transcript the event does carry holds the evidence. Measured 2026-09-16 over the 374 transcripts under `~/.claude/projects`: 206 carry at least one tool call, the longest sequence is 971 calls, the median non-empty one 19, and reading one costs about 4.5 ms.

`core/procedural_memory.mine_skills` mines *contiguous subsequences*, so order and repetition are the evidence. Two readers destroyed them: `scanner_parse.extract_message_stats` accumulated tool names into a set, and `scanner._parse_conversation_file` fed it from `read_head_tail`, a head-and-tail sample that would splice two halves of a session into one apparent sequence.

## Decision

`infrastructure/transcript_activity.py` reads a transcript as a stream and returns the ordered tool sequence, repetitions included, with the assistant turn count. `_build_session_entry` fills `toolsUsed` and `turnCount` from it when the event does not supply them; an event that carries either keeps its own value, and a missing or unreadable transcript leaves the entry as it was.

The sequence is capped at `MAX_TOOL_SEQUENCE = 2000` so one long session cannot dominate the session log, a cap the measured maximum of 971 sits under.

`scanner_parse` accumulates the sequence in a list rather than a set, and `scanner._parse_conversation_file` takes the sequence from the whole file instead of the head-and-tail sample it uses for metadata.

## Consequences

Easier: mining has an input. Measured on the same 374 transcripts, `mine_skills` returns 796 skills over the 206 sessions that carry a sequence, in 0.02 s; over a 120-transcript sample, the strongest were `Bash>ToolSearch` (32 sessions), `Agent>Bash` (27) and `Bash>Agent` (25). A session end now reads one transcript, about 4.5 ms.

`tests_py/infrastructure/test_transcript_activity.py` covers order and repetition, a session with turns but no tools, a malformed line, a missing transcript and the cap. `tests_py/hooks/test_session_lifecycle.py::TestSessionEntryActivity` covers the three entry cases. `tests_py/infrastructure/test_scanner.py` now expects `["Read", "Read"]` where it expected `["Read"]`: the repetition the set used to swallow.

Harder: every proficiency is 0.5 today. The session log records no outcome, so `mine_skills` treats every session as neutral and the smoothed success rate sits at its prior. Skills are recurrence without judgment until an outcome is recorded; that is the next step, not this one.

Unchanged: the 413 entries already in the log stay empty; they carry no transcript path to recover from.
