---
created: 2026-11-19T07:00:00Z
kind: adr
number: 1146
status: accepted
tags: [codex, lifecycle, durability, issue-716, amends-adr-1145]
title: The Codex drain hashes a relative rollout in the job directory and rescans
---
# ADR-1146: The Codex drain hashes a relative rollout in the job directory and rescans

## Status

accepted. Amends ADR-1145, decisions 1 and 2. Its replay check, its receipt and the delivery identity of ADR-1141 are unchanged.

## Context

Issue #716. The review of PR #1101 (Codex review, and the Notes of the Claude review) found three gaps in ADR-1145. The drain runs in the queue directory (`spawn`), while the lifecycle runs in the job's saved `cwd`: a relative `transcript_path` was hashed from the wrong directory, had no version, and its later versions were dropped as replays. Jobs of one `job_key` share its lock: a SessionEnd queued during a delivery had its own drain find the lock busy, and the holding drain's listing predated the new file, so the job waited for the next SessionStart `recover`. And a job dropped as a replay kept its `.error` file, which intake printed on every later run.

## Decision

1. The drain hashes a relative `transcript_path` from the job's saved `cwd`, the directory the lifecycle reads it from (`rollout_version.version(event, cwd)`).
2. A drain passes over the queue again while a pass delivered or removed a job. Each such pass removes at least one file, so the drain ends once no job it can take is left.
3. A job dropped as a replay clears its `.error` file, as a delivered one does.

## Consequences

Positive: a relative rollout is versioned like an absolute one, and a SessionEnd that lands during a delivery is drained before the drain exits (`tests_py/hooks/test_session_queue_versions.py`).

Negative: a drain that finished its pass lists the queue once more. A job that fails is retried in a later pass only while another job of the same drain is delivered. To go back, hash from the drain's directory, list the queue once and keep the `.error` of a replay.
