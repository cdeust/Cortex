---
created: 2026-11-04T18:00:00Z
kind: adr
number: 1123
status: accepted
tags: [recall, low-signal, tags, issue-706, amends-adr-0431]
title: User tags never hide a memory from default recall
---
# ADR-1123: User tags never hide a memory from default recall

## Status

accepted. Amends ADR-0431 (the low-signal tag filter of `recall_helpers.py`): the filter stays, its tag set is narrowed to capture markers.

## Context

Issue #706: `LOW_SIGNAL_TAGS` (ADR-0431) mixed two kinds of tags. Some are capture markers a Cortex writer puts on memories it records by itself: `auto-captured` and `tool:<name>` (`hooks/post_tool_capture.py`), `_backfill` (`handlers/backfill_memories.py`), `imported` (`core/session_extractor.py`, `handlers/wiki_seed_codebase.py`), `session-summary` (`handlers/record_session_end_memory.py`). The others, `audit`, `automated`, `wip`, `progress`, `code-review` and `stage-1` to `stage-11`, are copied from the wiki admission list `AUDIT_TAGS` (ADR-0296); no Cortex writer emits them (`grep` over `mcp_server/` and `scripts/` on main at 1de07f9). They are words a user may choose for their own memories, and a memory carrying one of them was dropped from default recall (`filter_low_signal`) and from trigger injection (`_injectable`).

The owner's rule in #706: user tags are never used to hide a user's own memories; the filter keys on a capture marker the system writes.

## Decision

1. `LOW_SIGNAL_TAGS` holds capture markers only: the tags listed above that a Cortex writer emits, the `tool:<name>` tags the filter already listed, and `tool-output`, which #706 lists among the capture tags.
2. `audit`, `automated`, `wip`, `progress`, `code-review` and `stage-1` to `stage-11` leave the recall filter. A memory carrying them is returned by default recall and can be injected by a trigger like any other memory.
3. The wiki admission list `AUDIT_TAGS` (ADR-0296) is unchanged: keeping a stage report out of the wiki is a different decision from hiding it from recall.
4. Not decided here, left on #706: whether default recall returns auto-captured memories labelled as such, whether the filter keys on the `source` column instead of tags, and the gap between `auto_recall` injection and `recall`.

## Consequences

Positive: a user's memory tagged `audit`, `wip` or `stage-3` is found by default recall; the filter no longer depends on vocabulary a user may choose.

Negative: memories that agents stored with stage-report tags (`stage-N`, `code-review`, `audit`) are now ranked in default recall with every other memory. If they crowd out curated memories, the fix is a system-written marker on those writes, not a user word in the filter.

Tests: `tests_py/handlers/test_recall_low_signal_filter.py` (each user-vocabulary tag is kept, the set is pinned to the capture markers) and `tests_py/handlers/test_inject_triggered_memories.py` (a trigger memory with a user-vocabulary tag is injected).
