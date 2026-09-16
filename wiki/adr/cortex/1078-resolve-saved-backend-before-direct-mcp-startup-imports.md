---
created: 2026-09-16T19:44:08Z
kind: adr
number: 1078
status: proposed
tags: [architecture, storage, codex, startup]
title: Resolve saved backend before direct MCP startup imports
---
# ADR-1078: Resolve saved backend before direct MCP startup imports

## Status

proposed

## Context

ADR-0505 resolves the saved backend in scripts/launcher.py. Direct console and python -m mcp_server startup skipped that resolution: Claude could honour a saved SQLite selection while Codex selected a reachable PostgreSQL server. PR #600 reproduces four failing bootstrap cases before the fix. Settings-dependent registry imports bind configuration early, so resolution inside main() would happen too late.

## Decision

Call the existing apply_backend_resolution(os.environ) at module startup before settings-dependent imports. Preserve precedence: explicit CORTEX_MEMORY_STORE_BACKEND, then CORTEX_BACKEND alias, then non-empty DATABASE_URL or CORTEX_MEMORY_DATABASE_URL, then saved methodology/backend.json, otherwise existing automatic selection. Retain the existing blank DATABASE_URL normalization. Importing this entry point intentionally mutates the process environment when resolution requires it. Keep the file-wide Ruff suppression scoped to E402 only: the intervening resolver call makes fourteen pre-existing downstream imports trigger E402, as independently measured in the PR review; one file-level explanation records this shared ordering constraint instead of fourteen repeated annotations.

## Consequences

Claude launcher and direct MCP startup apply the same saved backend policy without duplicating the resolver or merging existing stores. Explicit overrides remain authoritative. Tests isolate configuration roots and use subprocesses to avoid ambient environment leakage. Nine bootstrap cases pass after the fix; the reviewer reproduced four failures on the baseline and reported 8670 full-suite passes at db22b167. This establishes startup selection and tested process handoff, not installed-host hook parity, semantic retrieval quality, or PostgreSQL handoff. Project ADR sharing additionally requires a common physical project_root; lean authoring permissions remain unchanged. Evidence: https://github.com/cdeust/Cortex/pull/600#issuecomment-5703423724 and tests_py/test_shared_backend_bootstrap.py.
