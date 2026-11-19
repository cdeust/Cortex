---
created: 2026-11-19T06:20:00Z
kind: adr
number: 1145
status: accepted
tags: [codex, lifecycle, durability, issue-716, amends-adr-1144]
title: The Codex drain hashes the rollout and the receipt names the last version
---
# ADR-1145: The Codex drain hashes the rollout and the receipt names the last version

## Status

accepted. Amends ADR-1144, decisions 1 to 3: the intake no longer reads the rollout, and the replay check moves to the drain, against one receipt per delivery identity. The delivery identity (`job_key`, `session_end_event_id`, ADR-1141), the lifecycle's replacement (ADR-1143) and the profile dedup are unchanged.

## Context

Issue #716. ADR-1144 named a Codex job by its delivery identity and the SHA-256 of the rollout, hashed at intake, and kept one receipt per version. The review of PR #1100 (Codex review and the Claude review notes) found two defects in that design. The SessionEnd hook has three seconds (`plugins/hypermnesia-mcp-codex/hooks/hooks.json`), and the intake must make the event durable before anything slow (ADR-1084): hashing a large rollout first could exhaust that budget and lose the event. And a receipt per version dropped a rollout that went A, then B, then A again, on A's old receipt, while the session-log row stayed at B. A third case: `open()` raises `ValueError` on a path with a NUL byte, which escaped `enqueue`.

## Decision

1. The intake never reads the rollout. It persists the job as `<job_key>.json`, as under ADR-1141. An event that names a transcript is not dropped on an existing receipt; when `<job_key>.json` is still pending it is queued beside it as `<job_key>-<time_ns>.json`, since the pending job may already be reading older bytes. An event without a transcript keeps the ADR-1141 behaviour: dropped on a receipt or on a pending job.
2. The detached drain hashes the rollout (`scripts/rollout_version.py`, the `sha256` of `infrastructure/transcript_fingerprint.py` in the standard library) before it runs a job. There is one receipt per `job_key`; it holds the job and `transcript_sha256`, the version last delivered. The job is a replay, and is removed, when the receipt names the current hash, or when a receipt exists and the rollout cannot be read (a path `open` refuses included). Otherwise the lifecycle runs and the receipt is replaced, so A, then B, then A again reaches the lifecycle three times.
3. A receipt without `transcript_sha256` (written by ADR-1144's build, or unreadable) lets a readable rollout through once. A receipt of 4.24.0 is keyed on `sha256(session_id)` and matches no job of an event that names a transcript (ADR-1141, Consequences).

## Consequences

Positive: a Codex rollout that ended, was resumed and ended again reaches the lifecycle once per change of its bytes, a repeated delivery of the same bytes runs the lifecycle once, and the intake does no more work inside its budget than before ADR-1144 (`tests_py/hooks/test_session_queue_versions.py`).

Negative: the drain reads the whole rollout once per job, and a second delivery while a job is pending is a second job file, resolved by the drain. A version that changes between the drain's hash and the lifecycle's read is delivered again on the next SessionEnd and found to be a replay there. Not covered here, left on #716: native receipts per host (acceptance item 4). To go back, restore ADR-1144's `job_name` and per-version receipts.
