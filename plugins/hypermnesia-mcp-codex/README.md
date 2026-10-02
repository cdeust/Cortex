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
server and hooks through an explicitly prepared wheel environment. Install
`uv`, then prepare that runtime using the native Python:

```sh
python3 "<installed-plugin>/scripts/runtime.py" setup
```

The dispatcher checks the wheel version and isolates Python imports. Hooks
never resolve dependencies or compile packages.

## What it exposes

`.mcp.json` starts `hypermnesia-mcp` over stdio with no `--profile` flag, so
Codex gets the default `full` tool profile, the same surface the Claude Code
plugin serves.

`hooks/hooks.json` wires the 11 lifecycle hooks, each as
`python3 "${PLUGIN_ROOT}/scripts/runtime.py" <module>`
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

## Codex runtime setup and diagnosis (2 October 2026)

The bundled `scripts/runtime.py` dispatches hooks through the installed
`hypermnesia-mcp` uv tool environment and verifies its version against the plugin
manifest. An absent or mismatched runtime fails with an explicit setup message.
Hooks and SessionEnd replay do not resolve, download or compile dependencies.

Before trusting the hooks, install the matching wheel using the native Python:

```sh
python3 "<installed-plugin>/scripts/runtime.py" setup
```

Setup uses `uv tool install --python <the setup interpreter> --no-build`; use a
native interpreter on Apple Silicon. Source changes cannot repair an already
published wheel: the published Intel cryptography bound needs a future release.
After a plugin update, review changed definitions in the native `/hooks` browser.
Do not write trust hashes or bypass review. A prepared runtime or direct-hook
test proves neither native event delivery nor successful memory persistence.

The 2 October failure occurred before hook code loaded: unqualified uvx selected
Intel CPython on an ARM host and attempted cryptography compilation, then exceeded
5/10-second hook deadlines. See `docs/verification/codex-hooks-20261002.md`.
