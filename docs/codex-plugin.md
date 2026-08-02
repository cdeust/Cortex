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

The bundled MCP command is equivalent to:

```bash
uvx --from "hypermnesia-mcp[sqlite]" \
  hypermnesia-mcp --profile lean
```

This is a local plugin. It does not make Cortex available to ChatGPT web and
does not expose the local memory database over the internet.

## Public directory boundary

A future hosted Cortex integration is a separate security and product scope.
Public submission requires a stable HTTPS MCP Streamable HTTP endpoint,
authentication and per-user or per-organization isolation, reviewable tool
metadata, domain verification, operational monitoring, and the applicable
privacy and legal material. None of those remote-deployment claims are made by
this local package.
