# ADR-0050: Marketplace Is the Only Supported Install Path — uvx Removed

**Status:** Accepted
**Date:** 2026-04-25
**Supersedes:** the rationale in commit `9076fe5` ("adopt canonical uvx pattern")

## Context

Cortex has oscillated between two install paths over the past month:

| Version | MCP launch command | Hook command |
|---|---|---|
| v3.13.0 → v3.14.2 | `uvx` (PyPI) | `uvx` cortex-hook |
| v3.14.3 → v3.14.4 | `python3 scripts/launcher.py` | `python3 scripts/launcher.py` |
| v3.14.5 → v3.14.6 | `uvx` (PyPI) | `uvx` cortex-hook |
| v3.14.7+ | `bash $PY ${CLAUDE_PLUGIN_ROOT}/scripts/launcher.py` | same |

Commit `9076fe5` (2026-04-25) reintroduced uvx with the rationale:

> Researching Anthropic's reference servers shows the canonical pattern
> explicitly: every Python stdio MCP server in
> `modelcontextprotocol/servers` is wired up with `command: "uvx"`.

This rationale is **wrong for our distribution channel.** The
`modelcontextprotocol/servers` reference repository targets standalone
MCP servers added via `claude mcp add`, where the user separately
installs the package and Claude Code spawns it. That is a different
mechanism than the **plugin marketplace** (`/plugin install ...`),
which clones the plugin's git repository into
`~/.claude/plugins/cache/<marketplace>/<plugin>/<version>/` and
expects the plugin to launch from that directory.

uvx in a marketplace plugin is a category error: it bypasses the
material the marketplace already cloned and re-fetches code from PyPI
with separate version drift, separate caches, and separate failure
modes that don't exist in the marketplace path.

## Concrete failures observed with the uvx path

1. **Code-of-record divergence.** Edits to the marketplace clone (the
   `${CLAUDE_PLUGIN_ROOT}` Claude Code expands at launch) were never
   loaded. The running server fetched a stale wheel from PyPI. Every
   plugin update → reconnect cycle was a no-op for code changes that
   weren't yet on PyPI. Hours of debugging blamed Python module caching
   when the actual issue was that the marketplace clone wasn't on the
   import path at all.

2. **PEP 668 friction.** uvx triggered EXTERNALLY-MANAGED errors on
   homebrew Python and recent Debian/Ubuntu distributions. The launcher
   detour in v3.14.3/v3.14.4 was an attempt to fix that, then reverted
   in v3.14.5 with a regression of its own.

3. **Two-channel publish coupling.** Every release required PyPI
   publish to be coordinated with the marketplace clone. When PyPI
   credentials were missing or twine failed, the marketplace clone
   advertised a new version that uvx couldn't fetch — silent failure
   for end-users.

4. **Adversarial misuse.** AI sessions assisting Cortex maintenance
   would search the web, find the modelcontextprotocol/servers README,
   and propose "follow the canonical pattern" — the **wrong** pattern
   for a marketplace plugin — every time the maintainer asked about
   distribution. Without a written-down rule, this loop is infinite.

## Decision

**The plugin marketplace is the only supported Cortex install path.**
uvx is **not** removed because it is bad — it is removed because it is
**not Anthropic's official mechanism for plugin distribution**. The
marketplace was rolled out specifically so plugins could:

- Ship code, hooks, skills, and slash commands as a single git tree.
- Run from the cloned tree, not from a separate package channel.
- Stay in lockstep without two-channel publish coordination.
- Avoid PEP 668 entirely (no `pip install` step for users).

Cortex's release path now follows that contract:

```
.mcp.json::command           = "bash"
.mcp.json::args              = "-c", "$PY ${CLAUDE_PLUGIN_ROOT}/scripts/launcher.py mcp_server"
plugin.json::hooks[*].command = same shape, with the hook module name as the trailing arg
```

`scripts/launcher.py` lives in the plugin tree. It prepends
`${CLAUDE_PLUGIN_ROOT}` to `PYTHONPATH` and runs the module directly.
There is no PyPI fetch, no uvx step, no version drift.

## Consequences

- `pyproject.toml::[project.scripts]` no longer declares the
  `neuro-cortex-memory` or `cortex-hook` console scripts. The package
  is **not** published to PyPI.
- `mcp_server/hook_runner.py` is deleted (it existed solely to be the
  uvx target for `cortex-hook`).
- `mcp_server/doctor.py::_uvx_available` check is deleted. Doctor no
  longer reports uvx state because uvx state is no longer relevant.
- `mcp_server/infrastructure/mcp_client.py::_ALLOWED_COMMANDS` no
  longer accepts `"uvx"` or `"uv"` for sub-MCP-client spawns. CWE-78
  attack surface narrowed.
- `mcp_server/infrastructure/ap_bridge.py::_resolve_command` no longer
  has a uvx fallback. AP discovery returns `None` (graceful
  degradation) when no install can be found.

## Note to future AI assistants and contributors

If you propose reintroducing uvx because some Anthropic reference repo
("modelcontextprotocol/servers", "claude-code-plugins-cookbook", a blog
post, etc.) uses it — that reference is for a **different distribution
channel** (`claude mcp add` standalone servers). Cortex is a
**marketplace plugin** and the marketplace is the path. Read this ADR
first. Do not ship a PR that adds `uvx` to `.mcp.json`,
`.claude-plugin/plugin.json`, or any hook command.

## References

- `9076fe5` (commit that reintroduced uvx, now reverted)
- `8f76f85` (commit that removed every uvx invocation)
- Anthropic plugin marketplace documentation:
  https://docs.claude.com/en/docs/claude-code/plugins
