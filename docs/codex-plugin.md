# Cortex plugin for Codex

Cortex ships a native Codex package in an isolated repository subdirectory.
It exposes the same complete MCP tool profile and registers the same hook
modules as the Claude Code plugin. Host event payloads and timeout limits
differ, so registering the same modules does not guarantee identical behavior.
The adapters below handle those differences.

- **Same tool surface.** The Codex package starts the published PyPI server
  over local stdio with no `--profile` flag, so it gets the default `full`
  profile, exactly like the Claude Code plugin's server args, which also
  carry no `--profile` flag.
- **Same registered hook modules.** `hooks/hooks.json` wires all 11 lifecycle hooks
  that `mcp_server.hooks.entry.HOOK_MODULES` allows, which is the same set
  `.claude-plugin/plugin.json` wires for Claude Code. That allowlist is the
  single source of truth for the set; the contract tests import it through
  `tests_py/scripts/_codex_plugin_support.py` rather than restating it, and
  `tests_py/scripts/test_codex_plugin_hooks_contract.py` asserts both hosts
  dispatch exactly that set.

This reverses the earlier "Codex is additive, reduced" design that shipped an
MCP-only, `lean`-profile package.

## How the hooks run under Codex

A Codex plugin ships only its own directory, never this repository, and never
`scripts/launcher.py`, which is Claude-only. Runtime hooks invoke the
console script the wheel declares (`hypermnesia-mcp-hook`, `pyproject.toml`,
added in #605):

```bash
uvx --from "hypermnesia-mcp[postgresql,sqlite]==4.23.3" hypermnesia-mcp-hook <module>
```

`mcp_server/hooks/entry.py` validates `<module>` against `HOOK_MODULES`, wires
the composition root (issue #560), reads the one stdin event, normalizes it
(`mcp_server/hooks/host_event.py`, #608) and dispatches to the hook module
unchanged. Codex's `apply_patch` calls are expanded into one Edit/Write event
per file operation, `exec_command`/`shell_command` become a `Bash`-shaped
event, and `SubagentStart`'s `agent_type` is mapped to `agent_name`; a
Claude-shaped event passes through untouched.

Runtime commands check that `uvx` is present and report a named diagnostic if
it is missing. Session-end intake and startup recovery use the bundled
`${PLUGIN_ROOT}/scripts/session_queue.py` through Python 3. They do not import
the runtime before persisting or scheduling work.

The MCP server and runtime hooks pin the wheel to the plugin version. This
prevents a cached older wheel from silently handling newer event contracts.
CI builds that candidate wheel and supplies it through `UV_FIND_LINKS` before
the version is published; deployment uses the same requirement from PyPI.

### Event names and matchers

Event names are Codex's own, verified against
[learn.chatgpt.com/docs/hooks](https://learn.chatgpt.com/docs/hooks) (read
2026-09-22). Two differ from the Claude manifest:

- Codex has no `Notification` event. `compaction_checkpoint` is wired on
  `PreCompact`, which "runs before Codex compacts the chat", the module's own
  contract is to save a hippocampal checkpoint *before* compaction so state can
  be restored afterwards, so `PreCompact` is the matching point and
  `PostCompact` is not wired.
- `SessionEnd` carries `"timeout": 3`. Codex defaults `SessionEnd` to 1 second
  and "support[s] up to 3 seconds", the documented maximum, so the Claude
  manifest's 30 is not expressible here. The bundled intake persists the event before
  package startup and delegates recording to a replayable worker.

### Durable session-end recording

Codex's three-second ceiling applies to intake. A bundled Python standard-library
script writes and fsyncs the event before starting a detached worker. Package
resolution, transcript analysis and profile updates run in that worker. A new
session also starts recovery of pending events. The queue lives under
`$CORTEX_CLAUDE_DIR/methodology/session-end-queue` (default `~/.claude`).

Each event retains its storage selection. The worker uses the wheel version
from the installed plugin manifest. Session-log and profile writes carry replay
identities, so retrying an interrupted job does not apply either effect twice.
A worker failure retains the event and diagnostic; the next session reports
pending jobs and their worker log. Invalid existing lifecycle files remain
errors rather than being acknowledged as completed records.

See [ADR-1084](adr/ADR-1084-durable-sessionend-intake-before-package-startup.md)
for the persistence boundary and interruption tests. Consolidation remains a
separate detached operation; the durable receipt covers the session and profile
recording. Python 3 must be available on `PATH` for intake and recovery.

### Subagent briefing

The child-start hook supplies team decisions first, followed by prior context
for the child's role, within the existing briefing budget. Both passes enforce
project/global scope on PostgreSQL and SQLite. This works without a manual
memory call or special task wording.

When Codex exposes a plaintext `spawn_agent` or `Agent` task in `PreToolUse`,
Cortex retrieves against that exact message and appends the result while
preserving all other arguments. The installed collaboration path also emits
`collaborationspawn_agent`, but its message is encrypted. Cortex leaves that
argument untouched. Its native child receives explicitly labelled project/role
context through `SubagentStart`; Cortex does not claim task-specific retrieval
from an unavailable prompt or infer a task from another transcript.

See [ADR-1085](adr/ADR-1085-codex-task-and-project-briefings.md) for the captured
host contract and the two delivery paths.

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

That default is long, and these two are the hooks that hold up the tool call
while they run. A tighter ceiling would be worse, not better: both hosts
cancel a timed-out hook and discard its output, and Claude Code's reference
says plainly that a timed-out `PreToolUse` hook "doesn't block the tool call.
The call continues through the normal permission flow, so don't count on a
stalled hook to act as a gate." A timeout on a gate therefore fails **open**,
so a tight one would trade a rare long wait for silently ungated edits.
Warm, these cost 0.16s to 0.26s (measured 2026-09-22, same conditions as
above); the long wait is only the first cold `uvx` resolve, which the prewarm
removes. Note that this exposure is identical on Claude Code today, so it is
a property of both manifests rather than something Codex introduces.

Leaving the rest unset would not have been the parity case: on
`UserPromptSubmit`, a stalled `uvx` resolve or a blocked database would hold
up every prompt for ten minutes where Claude Code caps the same hook at five
seconds. For those, failing open is the right trade, because what a cancelled
run costs is one skipped enrichment. A cold `uv` cache will exceed those
budgets; prewarming (below) removes the window.

### Cost per edit

Every runtime hook is its own `uvx` process, so one `apply_patch`, `Edit` or `Write`
fires up to five of them: `decision_gate` and `no_deps_gate` before the call,
then `post_tool_capture`, `preemptive_context` and `pipeline_impact_bump`
after it. A patch touching several files still costs five processes, not five
per file: `host_dispatch` runs the module once per derived event inside a
single process.

Measured on 2026-09-22 (macOS 26.6.2 arm64, uv 0.11.3, warm `uv` cache,
published 4.23.1 wheel), one such process takes 0.18s to 0.21s in steady
state, with the first invocation of a given module slower (1.3s to 5.1s
observed) while its caches fill. The two gates are the ones in the blocking
path, at roughly 0.4s of that total. On a cold cache the first hook pays the
full resolve instead, which is what the prewarm below is for.

Matchers are widened to carry Codex's native tool names alongside Claude's.
The Codex docs state that for `apply_patch` "hook input still reports
`tool_name: "apply_patch"`", so every Edit/Write-triggered hook matches
`apply_patch` as well, and the `Bash`-triggered hook also matches
`exec_command|shell_command`.

File priming also recognizes explicit file operands in supported shell reads.
Paths resolve against the tool's working directory. Shell text is parsed, never
executed by the hook; ambiguous shell syntax and directory-wide searches do not
supply explicit file cues. A native PostToolUse event contains plain command
output without an exit code, so a cue identifies an attempted access to an
existing file, not a claim that the entire command succeeded. Native asynchronous
commands deliver that event after completion.

Priming updates each matching memory once per call, within the project's ancestor
scope or explicit global scope, on PostgreSQL and SQLite. Superseded, stale and
benchmark memories are excluded. See [ADR-1086](adr/ADR-1086-prime-project-memories-from-explicit-shell-file-cues.md)
for supported command forms and scope tests.

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
The first launch installs both storage drivers. Direct MCP startup reads the
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
uv tool install "hypermnesia-mcp[postgresql,sqlite]==4.23.3"
```

For the MCP server this is only a startup optimization, `startup_timeout_sec`
already covers a cold resolve. For the lifecycle hooks it matters more: every
hook is its own `uvx` invocation, so a cold cache makes the first one pay the
full package resolve. Prewarming removes that window. Session-end intake runs before package resolution; a cold worker keeps its event
queued until recording completes.

The bundled server declares `startup_timeout_sec: 180`. This is a bounded
startup ceiling, not a delay. Re-measured for the full profile on 2026-09-22
with `scripts/verify_mcp_hosts.py`, the same script and flags CI runs, the
exact two-driver command below completed `initialize`, `tools/list`, and a real
`memory_stats` call over **59 tools in 120.17 seconds** from clean
`UV_CACHE_DIR` and `UV_TOOL_DIR` directories on macOS 26.6.2 arm64 with uv
0.11.3. The next run from that cache completed the same contract in 4.24
seconds. CI reads the command, runtime policy, and timeout from the manifest
itself and repeats the clean-cache contract against the `full` profile.

The bundled MCP command is equivalent to:

```bash
env CORTEX_RUNTIME=cowork \
  uvx --from "hypermnesia-mcp[postgresql,sqlite]==4.23.3" \
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
