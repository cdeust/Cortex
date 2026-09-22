# Cortex plugin for Codex (`hypermnesia-mcp-codex`)

Persistent, local-first memory for Codex. This package points at the same
Cortex product as the Claude Code plugin: the complete MCP tool profile plus
the same 11 registered hook modules. Host event payloads and timeout limits
are handled by the adapters described in the linked documentation.

The full design, host boundary and measured startup contract are documented
in [docs/codex-plugin.md](https://github.com/cdeust/Cortex/blob/main/docs/codex-plugin.md).

## Install

```bash
codex plugin marketplace add cdeust/Cortex
codex plugin add hypermnesia-mcp-codex@cortex-codex-plugins
```

Restart the ChatGPT desktop app and start a new task. The plugin launches the
server and runtime hooks with `uvx`, so `uv` must be on `PATH`. Python 3
must also be on `PATH` for durable session-end intake. The first launch
resolves the `hypermnesia-mcp[postgresql,sqlite]` release from PyPI; later
launches run from the cache. Prewarming that cache is worth it, see
[docs/codex-plugin.md](https://github.com/cdeust/Cortex/blob/main/docs/codex-plugin.md):

```bash
uv tool install "hypermnesia-mcp[postgresql,sqlite]==4.23.4"
```

## What it exposes

`.mcp.json` starts `hypermnesia-mcp` over stdio with no `--profile` flag, so
Codex gets the default `full` tool profile, the same surface the Claude Code
plugin serves.

`hooks/hooks.json` wires the 11 lifecycle hooks, each as
`uvx --from "hypermnesia-mcp[postgresql,sqlite]==4.23.4" hypermnesia-mcp-hook <module>`
(or the bundled durable intake for session end):
session-start context injection, per-prompt auto-recall, auto-capture of
significant tool output, preemptive context, pipeline heat bumps, post-commit
reindexing, the decision and dependency edit gates, compaction checkpoints,
and the session-end record. Native subagents receive scoped team decisions and role context. Plaintext
spawn calls also receive task-specific briefing; opaque collaboration arguments
are preserved. Supported shell file reads prime
related memories in the current project. Session-end events are persisted before
package startup and processed by a detached, replayable worker. See the linked
design for supported command forms and recovery diagnostics.

## Storage

Cortex tries PostgreSQL at `DATABASE_URL` (or its local `cortex` default)
first and falls back to the zero-config SQLite store only when no explicit
PostgreSQL target was supplied. An explicitly configured but unreachable
`DATABASE_URL` is an error, never a silent redirect of your writes.

## Security expectations

- Local stdio only: no remote endpoint, no secrets in the manifest.
- Nothing leaves the machine except the one-time embedding-model download
  described in [PRIVACY.md](https://github.com/cdeust/Cortex/blob/main/PRIVACY.md).
- Vulnerability reports: see [SECURITY.md](./SECURITY.md).

## License

MIT, see [LICENSE](./LICENSE).
