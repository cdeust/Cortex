---
created: 2026-11-15T21:00:00Z
kind: adr
number: 1140
status: accepted
tags: [recall, low-signal, source, issue-706, amends-adr-1123, amends-adr-0431]
title: The low-signal filter keys on the writer's source, not on tags
---
# ADR-1140: The low-signal filter keys on the writer's source, not on tags

## Status

accepted. Amends ADR-1123 and ADR-0431: the filter of default recall and of trigger injection stays; it reads the `source` field instead of `LOW_SIGNAL_TAGS`, which is removed.

## Context

Issue #706 asks that user tags never hide a user's own memories, and that the filter key on a capture marker the system writes. ADR-1123 removed the words no Cortex writer emits from `LOW_SIGNAL_TAGS`, and left this point open (its decision 4). The set it kept (`auto-captured`, `tool:<name>`, `_backfill`, `imported`, `session-summary`, `tool-output`) is still a set of tags: a user who types one of them on their own memory loses it from default recall.

Each capture writer also sets `source` in the arguments it passes to `remember` (read on main at db035d8): `post_tool_capture` (`hooks/post_tool_capture.py`, `hooks/capture_worker_policy.py`), `backfill:<slug>` (`handlers/backfill_memories.py`), `import` (`handlers/import_sessions.py`), `seed:<rel>` (`handlers/wiki_seed_codebase.py`), `session` (`handlers/record_session_end_memory.py`). These are exactly the writers ADR-1123 names for the tags. PostgreSQL's `recall_memories` returns `source`; the SQLite recall projection (`sqlite_store_recall._result`) did not.

`memories.write_class` (ADR-0688) was considered and set aside: it does not cover this set. `auto` holds only `post_tool_capture`; `mechanical` also holds `ingest_codebase`, `ingest_prd` and the `wiki://` pointers, which default recall shows today; session summaries are `deliberate`.

## Decision

1. `shared/capture_source.py` holds the capture sources: `post_tool_capture`, `import`, `session`, and the prefixes `backfill:` and `seed:`. `is_capture_source` reads only that field.
2. `filter_low_signal` and `_injectable` (`handlers/recall_helpers.py`) drop a memory when `is_capture_source(source)` holds. Tags are not read. `LOW_SIGNAL_TAGS` is removed.
3. The SQLite recall projection returns `source`, as PostgreSQL already does.
4. The other half of the issue's "returns them labelled, or says how many it hid" is already met: `recall` returns `low_signal_dropped` (ADR-0430). Default recall keeps hiding captures; ADR-0431 is not reversed.
5. Not decided here, left on #706: the gap between `auto_recall` injection and `recall`, and its measurement in CI.

## Consequences

Positive: a user's memory is never hidden by any tag, including the former capture tags. What a capture writer records stays hidden exactly as before, since each writer's source is in the set.

Negative: a memory whose capture tag came from a writer that did not set one of these sources (an older Cortex, a hand-made import) is now returned by default recall. No such writer exists on main; existing stores were not measured. `tool-output`, which no writer emits, no longer hides anything. To go back, restore `LOW_SIGNAL_TAGS` and the two tag checks from the commit before this one.

Tests: `tests_py/handlers/test_recall_low_signal_filter.py` (each writer's source is dropped, each former capture tag on a user memory is kept, the set is pinned), `tests_py/handlers/test_inject_triggered_memories.py`, `tests_py/infrastructure/test_sqlite_recall_source.py` (the SQLite projection carries `source` and the filter reads it).
