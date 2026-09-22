# Cortex plugin for Codex

Cortex ships a native Codex package in an isolated repository subdirectory.
It points at the same Cortex product as the existing Claude Code plugin, and
both packages expose the same product: **Cortex behaves the same under Codex
as under Claude Code.**

- **Same tool surface.** The Codex package starts the published PyPI server
  over local stdio with no `--profile` flag, so it gets the default `full`
  profile — exactly like the Claude Code plugin's server args, which also
  carry no `--profile` flag.
- **Same lifecycle hooks.** `hooks/hooks.json` wires all eleven hook modules
  that `mcp_server.hooks.entry.HOOK_MODULES` allows, which is the same set
  `.claude-plugin/plugin.json` wires for Claude Code. That allowlist is the
  single source of truth for the set; the contract test in
  `tests_py/scripts/test_codex_plugin_contract.py` imports it rather than
  restating it.

This reverses the earlier "Codex is additive, reduced" design that shipped an
MCP-only, `lean`-profile package.

## How the hooks run under Codex

A Codex plugin ships only its own directory — never this repository, and never
`scripts/launcher.py`, which is Claude-only. Each hook therefore invokes the
console script the wheel declares (`hypermnesia-mcp-hook`, `pyproject.toml`,
added in #605):

```bash
uvx --from "hypermnesia-mcp[postgresql,sqlite]" hypermnesia-mcp-hook <module>
```

`mcp_server/hooks/entry.py` validates `<module>` against `HOOK_MODULES`, wires
the composition root (issue #560), reads the one stdin event, normalizes it
(`mcp_server/hooks/host_event.py`, #608) and dispatches to the hook module
unchanged. Codex's `apply_patch` calls are expanded into one Edit/Write event
per file operation, `exec_command`/`shell_command` become a `Bash`-shaped
event, and `SubagentStart`'s `agent_type` is mapped to `agent_name`; a
Claude-shaped event passes through untouched.

Each command is wrapped in a `uvx` presence check. That is the only thing that
can go wrong at this command line that the plugin can diagnose: unlike the
Claude manifest there is no `CLAUDE_PLUGIN_ROOT` to guard (nothing in the
command resolves against the plugin root) and no interpreter to locate (`uvx`
owns the environment). A missing `uv` therefore reports a named cause on
stderr and exits 1 instead of surfacing a bare `command not found`.

### Event names and matchers

Event names are Codex's own, verified against
[learn.chatgpt.com/docs/hooks](https://learn.chatgpt.com/docs/hooks) (read
2026-09-22). Two differ from the Claude manifest:

- Codex has no `Notification` event. `compaction_checkpoint` is wired on
  `PreCompact`, which "runs before Codex compacts the chat" — the module's own
  contract is to save a hippocampal checkpoint *before* compaction so state can
  be restored afterwards, so `PreCompact` is the matching point and
  `PostCompact` is not wired.
- `SessionEnd` carries `"timeout": 3`. Codex defaults `SessionEnd` to 1 second
  and "support[s] up to 3 seconds" — the documented maximum, so the Claude
  manifest's 30 is not expressible here. `session_lifecycle` survives that
  ceiling because it spawns its consolidation as a detached subprocess (#610)
  rather than doing the work inline.

### Timeouts

A latency budget is part of how a hook behaves, so every other budget is the
Claude manifest's own number: `session_start` 30s, `auto_recall` 5s,
`post_tool_capture` 10s, `preemptive_context` 5s, `pipeline_impact_bump` 5s,
`post_commit_reindex` 10s, `compaction_checkpoint` 10s, `agent_briefing` 5s.
Codex documents a special default and maximum only for `SessionEnd` and
`Interrupt`, so all of those are settable.

`decision_gate` and `no_deps_gate` declare none, because the Claude manifest
declares none for them either and both hosts default a command hook to 600
seconds. Declaring nothing on both sides is the parity case, not an omission.

Leaving the rest unset would not have been: on `UserPromptSubmit`, a stalled
`uvx` resolve or a blocked database would hold up every prompt for ten
minutes where Claude Code caps the same hook at five seconds.

The tradeoff is that a cold `uv` cache will exceed these budgets, and a hook
that exceeds its timeout is cancelled with its output discarded. That costs
one skipped enrichment, never a blocked prompt or a blocked edit; Claude
Code's own reference is explicit that a timed-out `PreToolUse` hook "doesn't
block the tool call". Prewarming the cache (below) removes the window.

Matchers are widened to carry Codex's native tool names alongside Claude's.
The Codex docs state that for `apply_patch` "hook input still reports
`tool_name: "apply_patch"`", so every Edit/Write-triggered hook matches
`apply_patch` as well, and the `Bash`-triggered hook also matches
`exec_command|shell_command`.

The Codex `.mcp.json` lives under `plugins/hypermnesia-mcp-codex/`, never at
the repository root. The package directory also carries its own `README.md`,
`SECURITY.md`, `LICENSE`, `.codexignore` and `assets/` (icon, screenshots):
plugin registries score each package on what is inside that directory, not
on the repository root, so those files are duplicated there on purpose. This preserves Cortex's Claude contract: Claude Code
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
The first launch installs both storage drivers. In this source checkout (pending
release), direct MCP startup reads the
same `~/.claude/methodology/backend.json` selection as the Claude launcher
before loading memory settings. `CORTEX_CLAUDE_DIR` relocates that shared
configuration root. Explicit `CORTEX_MEMORY_STORE_BACKEND`, then
`CORTEX_BACKEND`, then a non-empty `DATABASE_URL` or
`CORTEX_MEMORY_DATABASE_URL` take precedence over the saved selection.

Without a saved selection or explicit backend, Cortex keeps its existing
`auto` behavior: PostgreSQL first, then SQLite only when no explicit PostgreSQL
target was supplied and the default server is unavailable. An explicitly
configured but unreachable database URL remains an error rather than silently
redirecting writes. Both hosts must use the same configuration root and storage
settings to share memories; this does not merge previously separate stores.

A prewarm downloads the package before restarting Codex:

```bash
uv tool install "hypermnesia-mcp[postgresql,sqlite]"
```

For the MCP server this is only a startup optimization — `startup_timeout_sec`
already covers a cold resolve. For the lifecycle hooks it matters more: every
hook is its own `uvx` invocation, and `SessionEnd` cannot be given more than
Codex's 3-second maximum, so a cold cache at session end can lose that one
hook's run. Prewarming removes that window.

The bundled server declares `startup_timeout_sec: 180`. This is a bounded
startup ceiling, not a delay. Re-measured for the full profile on 2026-09-22
with `scripts/verify_mcp_hosts.py` — the same script and flags CI runs — the
exact two-driver command below completed `initialize`, `tools/list`, and a real
`memory_stats` call over **59 tools in 120.17 seconds** from clean
`UV_CACHE_DIR` and `UV_TOOL_DIR` directories on macOS 26.6.2 arm64 with uv
0.11.3. The next run from that cache completed the same contract in 4.24
seconds. CI reads the command, runtime policy, and timeout from the manifest
itself and repeats the clean-cache contract against the `full` profile.

The bundled MCP command is equivalent to:

```bash
env CORTEX_RUNTIME=cowork \
  uvx --from "hypermnesia-mcp[postgresql,sqlite]" \
  hypermnesia-mcp
```

`CORTEX_RUNTIME=cowork` selects Cortex's existing DB-optional local-runtime
policy; it does not install or invoke the Cowork plugin. The Claude Code
plugin manifest, hooks, agents, and tool profile are unchanged by this
package. The shared Claude marketplace catalog changes only to publish
`hypermnesia-mcp-viz` and retain `cortex-viz` as a frozen, nonfunctional
migration shim.

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

See [shared memory and decisions](shared-host-memory.md) for the common storage
and ADR-root contract, opt-in authoring, and the limits of the handoff tests.
