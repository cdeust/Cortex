---
title: Transcript capture producers — 2026-11-05
status: complete (inventory); acceptance tests and any cursor are later slices of #716
owners: engineer
---

# Transcript capture producers (2026-11-05)

## Why this audit exists

Issue #716 asks whether Cortex has a replayable append contract for
transcript capture: one logical session spread over several Codex rollout
files, late or repeated delivery, an earlier turn rewritten, an
acknowledgement lost after a write. Its first step is "audit all capture
producers first; reuse any existing cursor/idempotency mechanism". This is
that audit. It changes no code. Every claim cites the line read at `main`
`2126d2a`; a claim marked *inferred* follows from the cited lines but was
not executed.

## Summary

- **No producer keeps a cursor into a transcript.** No byte offset, line
  count or last-seen turn is persisted anywhere. The progress markers that
  exist are: a hash of the first 64 KiB of a file (P3), the transcript stem
  or `sha256(session_id)` (P1), spool and queue files (P1, P2), and the
  exact-content dedup of `remember` (P2, P3, P4).
- **Nothing discovers Codex rollouts.** A rollout is read only when a
  SessionEnd payload hands over its `transcript_path`; the discovery walks
  of P3 and P4 cover `CLAUDE_DIR/projects` only.
- **No producer captures rollout text into memories.** The only reader of a
  rollout (P1) extracts tool names and the assistant turn count, never
  message text (`mcp_server/infrastructure/transcript_rollout.py:1-14`).
- Consequence for #716: its four acceptance items have no existing
  mechanism to reuse for message content. The decision the issue names in
  *Alternatives considered* (build a cursor, or document the limits and
  close) is the owner's; the facts below are what that decision rests on.

## P1. SessionEnd (`mcp_server/hooks/session_lifecycle.py`)

- **Trigger.** Claude Code SessionEnd hook; Codex SessionEnd →
  `plugins/hypermnesia-mcp-codex/scripts/session_queue.py` intake, drained
  by a detached worker.
- **Input.** The hook payload; when it carries no tools or turns, the whole
  transcript is re-read (`session_lifecycle.py:233-238`). Output: one
  session-log row and one profile update, no memory rows.
- **Session identity — two keys.** The log row is keyed by the transcript
  file stem, falling back to `session_id`
  (`session_lifecycle.py:240-241`, `mcp_server/shared/injection_markers.py:41-47`); the
  profile update is keyed by `sha256(session_id)`
  (`session_lifecycle.py:359-372`). *Inferred:* a Codex session continued
  into a second rollout file gets two log rows but one profile update, so
  the second file's activity never reaches the profile — acceptance item 1
  of #716 fails on the profile path.
- **Duplicate delivery.** Log row skipped when its `sessionId` is already
  present (`session_lifecycle.py:257-258`), but only the last 1000 rows are
  kept (`:259-261`), so a replay older than that window appends again
  (*inferred*). Codex intake: an existing receipt short-circuits, and
  `os.link` never overwrites a queued job (`session_queue.py:97-111`).
- **Rewrite of an earlier turn.** Not detected. *Inferred:* a transcript
  that ends a second time under the same stem keeps its first row; the
  later activity is dropped.
- **Ack loss.** Replay-safe by ADR-1084: the receipt is written only after
  the worker exits 0 (`session_queue.py:201-204`), and the two dedups above
  absorb the replay.
- **Tests.** `tests_py/hooks/test_session_end_replay.py`,
  `tests_py/hooks/test_session_queue.py`,
  `tests_py/hooks/test_session_lifecycle.py`,
  `tests_py/infrastructure/test_transcript_rollout.py`. None covers a
  session spanning two rollout files, nor a rewritten prefix.

## P2. PostToolUse (`mcp_server/hooks/post_tool_capture.py` → capture worker or spool)

- **Input.** `tool_name`, `tool_input`, `tool_response` of one event; the
  transcript is not read. No `session_id` travels in the remember payload.
- **Duplicate delivery.** Exact-replay dedup in `remember`, keyed by
  content plus scope fields (`mcp_server/infrastructure/memory_exact_sql.py`,
  `mcp_server/handlers/remember.py`); tags and timestamps are not in the key.
- **Ack loss.** Spool: a file is deleted only after `store` returns
  (`mcp_server/hooks/capture_drain.py`), so replay is at-least-once and
  absorbed by the dedup. Resident worker: the server acknowledges once the
  payload is in its in-memory queue (`mcp_server/infrastructure/capture_server.py:56-58`), before it
  is stored, and the client never replays an uncertain delivery
  (`mcp_server/infrastructure/capture_client.py:39`). *Inferred:* a worker crash after the ack
  loses the capture rather than duplicating it.
- **Rewrite.** Not applicable: one event, one memory.

## P3. `backfill_memories` (also SessionStart cold-start `_auto_backfill`)

- **Input.** `CLAUDE_DIR/projects/**/*.jsonl`, each file read as head and
  tail, not whole.
- **Progress.** Table `backfill_log(file_path UNIQUE, file_hash)`; the hash
  is sha256 of the first 64 KiB, truncated to 16 hex chars
  (`mcp_server/handlers/backfill_helpers.py:79-84`). The row is written
  after the file's items, and only if `imported > 0 or skipped == 0`
  (`mcp_server/handlers/backfill_memories.py:339-345`).
- **Rewrite / append.** *Inferred:* any change past the first 64 KiB leaves
  the hash unchanged, so a long transcript that grows is never re-read.
- **Ack loss.** A crash before `mark_backfilled` re-reads the file; items
  of identical text are absorbed by the exact dedup, others duplicate
  (*inferred*; the module docstring concedes duplicates).

## P4. `import_sessions`

- No progress marker: every run re-reads every top-level Claude transcript.
  Exact dedup only; non-identical re-extraction duplicates (*inferred*). No
  idempotency test.

## P5. Compaction checkpoint (`mcp_server/hooks/compaction_checkpoint.py`)

- Stores the hook payload as one checkpoint row keyed by transcript stem or
  `session_id`. No dedup and no replay test found.

## What a later slice of #716 can reuse

- ADR-1084's queue-then-receipt pattern (P1) is the only replay-safe
  delivery in the tree; it is keyed by `session_id`, not by file, which is
  the right key for a multi-file Codex session but is not applied to the
  session-log row.
- The exact-replay dedup (P2) absorbs identical replays only; it cannot
  express "turn N of session S was replaced".
- Nothing here implements a durable cursor, prefix-rewrite detection or
  rollout discovery; those would be new mechanisms and need the owner's
  product decision first (#716, *Alternatives considered*).
