# Cortex plugin for Codex (`hypermnesia-mcp-codex`)

Persistent, local-first memory for Codex. This package points at the same
Cortex product as the Claude Code plugin, but exposes only the MCP server:
no lifecycle hooks, skills, apps or agents. Claude Code remains the primary
integration; Codex is additive.

The full design, host boundary and measured startup contract are documented
in [docs/codex-plugin.md](https://github.com/cdeust/Cortex/blob/main/docs/codex-plugin.md).

## Install

```bash
codex plugin marketplace add cdeust/Cortex
codex plugin add hypermnesia-mcp-codex@cortex-codex-plugins
```

Restart the ChatGPT desktop app and start a new task. The plugin launches the
server with `uvx`, so `uv` must be on `PATH`. The first launch resolves the
`hypermnesia-mcp[postgresql,sqlite]` release from PyPI; later launches run
from the cache.

## What it exposes

The `.mcp.json` in this directory starts `hypermnesia-mcp --profile lean` over
stdio. The lean profile is exactly these ten tools:

`query_methodology`, `remember`, `recall`, `unified_search`,
`recall_hierarchical`, `consolidate`, `memory_stats`, `check_setup`,
`wiki_read`, `wiki_list`.

Every one of them is read-only or an idempotent write; no destructive tool
(`forget`, `wiki_purge`, `wiki_migrate`) is part of the profile.

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

MIT — see [LICENSE](./LICENSE).
