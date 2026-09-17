---
created: 2026-09-17T09:22:42Z
kind: adr
number: 1080
status: accepted
tags: [hooks, memory-scoping, session-start, auto-recall]
title: Inject only the session's project and global memories in session hooks
---
# ADR-1080: Inject only the session's project and global memories in session hooks

## Status

accepted

## Context

`auto_recall` (per-prompt injection) and `session_start` (session banner)
queried memories with no project predicate on either storage backend. A
session started under one project received the hot and protected memories
of every project the store held, observed directly (#604) and confirmed by
an outside review of Cortex. The store already carries a
`directory_context` column on every memory and the PostgreSQL `recall`
function already scopes by it; the two hooks bypassed that column
entirely.

## Decision

A memory is injected into a session only when it is global, or its
`directory_context` equals the session's project root, or its
`directory_context` is an ancestor of the session's project root. An
empty `directory_context` is not a wildcard for every project. Team
decisions stay global by design and are unaffected.

The session's project root comes from the `CLAUDE_PROJECT_ROOT`
environment override when set, otherwise from the hook event's `cwd`
field. When neither is available the hook logs that it could not resolve
a project root and restricts injection to global memories, never
everything.

The rule is one pure function, `memory_matches_project` in
`mcp_server/shared/project_scope.py`, with a companion
`resolve_project_root` and `project_ancestors`. Both hooks and both
storage backends call it: the PostgreSQL queries fetch `directory_context`
and `is_global` alongside their existing columns and filter the returned
rows in Python; the SQLite store rows already carry both columns, so the
same filter applies directly. No SQL predicate is duplicated across the
four call sites, and no store schema or generic store method changed.

## Consequences

Positive: a session under one project no longer sees another project's
hot or protected memories. The failure mode when a project root cannot be
resolved degrades to global-only injection instead of silent leakage.

Negative: memories written before this fix with an empty
`directory_context` and no `is_global` flag stop being injected by these
two hooks until re-scoped or promoted to global; they remain reachable
through the `recall` tool, which this change does not touch.
