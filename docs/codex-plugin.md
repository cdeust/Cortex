# Cortex plugin for Codex

Cortex ships a native Codex package in an isolated repository subdirectory.
It points at the same Cortex product as the existing Claude Code plugin, but
the two packages deliberately offer different host integrations:

- **Claude Code is primary.** Its marketplace package keeps automatic hooks,
  custom agents, the complete MCP tool profile, and the existing installation
  flow.
- **Codex is additive.** Its MCP-only package starts the published PyPI server
  over local stdio with the exact 10-tool `lean` profile. It installs no
  lifecycle hooks, skills, apps, or agents and does not alter the Claude
  package.

The Codex `.mcp.json` lives under `plugins/hypermnesia-mcp-codex/`, never at
the repository root. This preserves Cortex's Claude contract: Claude Code
must not discover a second project-scoped MCP server when this repository is
the active working directory.

## Install from the repository marketplace

Add the Cortex repository marketplace and install the plugin:

```bash
codex plugin marketplace add cdeust/Cortex
codex plugin add hypermnesia-mcp-codex@cortex-codex-plugins
```

Restart the ChatGPT desktop app and start a new task so Codex loads the new
plugin components. The plugin uses `uvx`, so `uv` must be available on `PATH`.
The first launch installs both storage drivers. Cortex tries PostgreSQL first
at the configured `DATABASE_URL` (or its local `cortex` default), then falls
back to SQLite only when no explicit PostgreSQL target was supplied and the
default server is unavailable. An explicitly configured but unreachable
`DATABASE_URL` remains an error rather than silently redirecting writes.

An optional prewarm can download the package before restarting Codex; it is a
startup optimization, not an installation prerequisite:

```bash
uv tool install "hypermnesia-mcp[postgresql,sqlite]"
```

The bundled server declares `startup_timeout_sec: 180`. This is a bounded
startup ceiling, not a delay. On 2026-08-03, the exact two-driver command below
completed `initialize`, `tools/list`, and a real PostgreSQL-backed
`memory_stats` call in 103.84 seconds from clean `UV_CACHE_DIR` and
`UV_TOOL_DIR` directories on macOS 26.5.1 arm64 with uv 0.8.19. It exposed
exactly ten lean tools. The next offline run from that cache completed the same
contract in 2.75 seconds. CI reads the command, runtime policy, and timeout from
the manifest itself and repeats the clean-cache contract.

The bundled MCP command is equivalent to:

```bash
env CORTEX_RUNTIME=cowork \
  uvx --from "hypermnesia-mcp[postgresql,sqlite]" \
  hypermnesia-mcp --profile lean
```

`CORTEX_RUNTIME=cowork` selects Cortex's existing DB-optional local-runtime
policy; it does not install or invoke the Cowork plugin. Claude Code remains
the primary integration, and its primary plugin manifest, hooks, agents, and
full tool profile are unchanged. The shared Claude marketplace catalog changes
only to publish `hypermnesia-mcp-viz` 3.0.0 and retain `cortex-viz` as a frozen,
nonfunctional migration shim.

This is a local plugin. It does not make Cortex available to ChatGPT web and
does not expose the local memory database over the internet.

The repository-marketplace schema requires both `policy.installation` and
`policy.authentication`. Cortex uses the documented `ON_INSTALL` value. This
is marketplace timing metadata, not an added authentication mechanism: the
local stdio server declares no credentials or remote endpoint, and the
non-interactive install is exercised in CI. See OpenAI's
[marketplace metadata contract](https://developers.openai.com/plugins/build/plugins#marketplace-metadata).

## Public directory boundary

A future hosted Cortex integration is a separate security and product scope.
Public submission requires a stable HTTPS MCP Streamable HTTP endpoint,
authentication and per-user or per-organization isolation, reviewable tool
metadata, domain verification, operational monitoring, and the applicable
privacy and legal material. None of those remote-deployment claims are made by
this local package.
