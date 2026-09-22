# Shared memory and decisions across Claude and Codex

## What this change establishes

Claude and Codex can connect independent Cortex MCP processes to the same
storage and decision files. The direct console entry point now applies the
saved backend selection before importing memory settings, matching the Claude
launcher (ADR-0505). Previously, a saved SQLite selection could be ignored by
the direct entry point: its automatic selection could choose a reachable local
PostgreSQL server instead.

This is a source-checkout change. Installing the currently published package
does not establish that this fix is present; it must be released first.

## Shared configuration contract

Both processes need the same backend and physical storage location. For an
isolated SQLite evaluation, set these variables identically in both launches:

```sh
export CORTEX_CLAUDE_DIR=/absolute/path/to/disposable-cortex
export CORTEX_MEMORY_STORE_BACKEND=sqlite
export CORTEX_MEMORY_DB_PATH="$CORTEX_CLAUDE_DIR/memory.db"
export CORTEX_MEMORY_SQLITE_FALLBACK_PATH="$CORTEX_CLAUDE_DIR/memory.db"
```

These paths are examples for disposable data. This workflow neither migrates
nor merges existing databases. PostgreSQL deployments must likewise use the
same explicit database target; cross-process PostgreSQL handoff is not covered
by the new SQLite tests.

Backend precedence remains: explicit `CORTEX_MEMORY_STORE_BACKEND`, then
`CORTEX_BACKEND`, then a non-empty database URL, then the saved
`methodology/backend.json` selection. Without these, existing automatic
selection remains unchanged. An explicit unreachable PostgreSQL target must
not silently redirect writes to SQLite.

## ADRs also need shared files

A shared database alone does not share project decision records. Project-mode
`wiki_adr` stores files under the supplied absolute `project_root`, updates the
project decision index, and returns `memory_sync: project-files-only`
(ADR-0056). Both clients must pass the same physical project root with a valid
`wiki/manifest.json`. Matching project labels in separate worktrees do not
make their files shared.

Use exact ADR identifiers for handoff. A missing or stale index fails closed;
initialize or repair it with `wiki_reindex` before relying on exact lookup.
For global wiki operations, the shared `CORTEX_CLAUDE_DIR` also determines the
wiki root.

## Tool permissions

The bundled Codex plugin serves the default `full` profile, so it can author a
project ADR as well as recall one, exactly like the Claude Code plugin. A
process started with `--profile lean` (or `CORTEX_MCP_PROFILE=lean`) can recall
a project ADR but cannot create one, because `lean` hides and rejects the wiki
writers (ADR-0693). Neither profile is a narrowly scoped decision-writing
surface: `full` exposes every tool, and `lean` exposes the recall subset.

A minimal evaluation is:

1. A full-profile client creates a project ADR with `wiki_adr`.
2. A second client recalls its exact identifier using the same `project_root`.
3. Another full-profile client writes a follow-up ADR that cites the first and
   describes the observed outcome.
4. Both clients retrieve the follow-up and its reference.

The follow-up reference is explicit text. These tests do not establish
automatic outcome attribution or automatic conflict resolution. Both hosts do
now install the same 11 lifecycle hooks (`docs/codex-plugin.md`), but that
parity is asserted by the plugin contract tests, not by the handoff tests
here.

## Reproducible checks

The added tests use disposable roots and independent processes:

- `tests_py/test_shared_backend_bootstrap.py`: saved selection and explicit
  override precedence at direct entry-point startup. Before the fix, four of
  nine cases failed; after the fix all nine pass.
- `tests_py/test_shared_host_decisions.py`: actual MCP calls for full-to-lean
  exact ADR handoff, denied lean authoring, linked follow-up, simultaneous ADR
  allocation, and separation between two explicit project roots.
- `tests_py/infrastructure/test_shared_host_store.py`: independent SQLite
  processes observe acknowledged writes, retain distinct concurrent records,
  and read persisted content after reopening.

Run these with the repository Python environment and
`CORTEX_MEMORY_STORE_BACKEND=sqlite`. The storage test bypasses embedding and
semantic retrieval; its assertions concern committed rows. The MCP clients
are test clients, not installed Claude or Codex applications. Project-root
separation is a routing check, not an authorization boundary.

### Test liveness policy

The test harness uses 30-second bootstrap and protocol deadlines, a 90-second
MCP scenario deadline, and 5 seconds per shutdown stage. These are engineering
time budgets to fail stalled tests and clean up children before the existing
300-second pytest ceiling, not algorithm constants or latency benchmarks.

Validation on the local macOS checkout: all 12 new tests and 47 related
backend, launcher, profile, and ADR tests passed. Ruff lint, formatting,
and the craftsmanship gate passed. The store protocol test uses POSIX pipe
selection; these results do not establish Windows coverage. Independent review
approved the change after subprocess deadlines and cleanup were added.

## Next acceptance step

Run the released or explicitly checkout-backed server through both installed
hosts against a disposable store. Verify the configured roots, available
tools, decision creation, exact retrieval, and outcome handoff. Only then
assess packaging changes and a public directory submission. No live host
configuration, personal memory data, or marketplace listing is changed here.
