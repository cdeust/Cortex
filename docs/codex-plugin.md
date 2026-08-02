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
uv tool install "hypermnesia-mcp[sqlite]"
codex plugin marketplace add cdeust/Cortex
codex plugin add hypermnesia-mcp-codex@cortex-codex-plugins
```

Restart the ChatGPT desktop app and start a new task so Codex loads the new
plugin components. The plugin uses `uvx`, so `uv` must be available on `PATH`.
The preliminary `uv tool install` is deliberate: it downloads the published
package before Codex's startup window, allowing the first plugin handshake to
reuse uv's local artifact cache.

The bundled server declares `startup_timeout_sec: 180`. This is a bounded
startup ceiling, not a delay. On 2026-08-02, a local macOS 26.5.1 arm64 run
with uv 0.8.19 and clean `UV_CACHE_DIR` and `UV_TOOL_DIR` completed
`initialize`, `tools/list`, and `memory_stats` in 110.46 seconds with exactly
ten lean tools. A follow-up on the same machine after the tool installation
completed the same contract in 28.19 seconds. The clean `ubuntu-latest` CI
runner completed it in 23.87 seconds; CI reads the command and timeout from the
manifest itself.

The bundled MCP command is equivalent to:

```bash
uvx --from "hypermnesia-mcp[sqlite]" \
  hypermnesia-mcp --profile lean
```

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
