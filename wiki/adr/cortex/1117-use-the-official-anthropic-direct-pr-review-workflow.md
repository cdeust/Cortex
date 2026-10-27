---
created: 2026-10-27T18:47:20Z
kind: adr
number: 1117
status: proposed
tags: [ci, claude, supersedes-adr-1116]
title: Use the official Anthropic direct PR review workflow
---
# ADR-1117: Use the official Anthropic direct PR review workflow

## Status

proposed

## Context

ADR-1116 introduced a custom workflow_run Claude review protocol. The owner explicitly rejected this architecture and requested the official anthropics/claude-code-action README and workflow. Run40553919216 failed before review because subprocess environment scrubbing requires bubblewrap.

## Decision

Replace Claude workflow_run with pull_request opened, synchronize, reopened and ready_for_review. Copy the upstream review-pr command and its five reviewer agents verbatim from8041f1d17e0e7d2f2cfe35002962e9f26237c0bb. Adapt only runner, existing OAuth auth, pinned actions and progress tracking; install bubblewrap. Retire custom Claude attestation markers, readers and combined proof. Preserve native Codex evidence and trusted resolver checks. Preserve owner-only mention invocation on owner-authored threads.

## Consequences

This supersedes ADR-1116's custom Claude execution and evidence architecture. Claude reports through native PR comments and its Actions check. The App validates workflow content against main, so bootstrap cannot prove native acceptance; verify actual review execution after configuration reaches main before requiring the native Claude check. No fabricated review or status is accepted.
