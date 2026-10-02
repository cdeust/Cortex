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

The bundled `scripts/runtime.py` checks the installed uv tool's wheel version
and executes its isolated interpreter (`-I`). The hook command is:

```sh
python3 "${PLUGIN_ROOT}/scripts/runtime.py" <module>
```

No event resolves dependencies, downloads packages or compiles native extensions.
Setup prepares the environment separately; absent or stale installations fail
with a named setup diagnostic. The wheel's `mcp_server/hooks/entry.py` validates
the hook module and wires the configured backend. SessionEnd first persists
its event using the bundled standard-library queue, then invokes this same
runtime in a replayable worker. No repository module can shadow the wheel.

## Event names and matchers

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
above). The current Codex dispatcher requires prepared dependencies;
no package resolution occurs during an event.

Leaving the rest unset would not have been the parity case: on
`UserPromptSubmit`, a blocked database would hold
up every prompt for ten minutes where Claude Code caps the same hook at five
seconds. For those, failing open is the right trade, because what a cancelled
run costs is one skipped enrichment. An absent runtime is reported immediately with the setup instruction.

### Cost per edit

Every runtime hook is its own Python process, so one `apply_patch`, `Edit` or `Write`
fires up to five of them: `decision_gate` and `no_deps_gate` before the call,
then `post_tool_capture`, `preemptive_context` and `pipeline_impact_bump`
after it. A patch touching several files still costs five processes, not five
per file: `host_dispatch` runs the module once per derived event inside a
single process.

Measured on 2026-09-22 (macOS 26.6.2 arm64, uv 0.11.3, warm `uv` cache,
published 4.23.1 wheel), one such process takes 0.18s to 0.21s in steady
state, with the first invocation of a given module slower (1.3s to 5.1s
observed) while its caches fill. The two gates are the ones in the blocking
path, at roughly 0.4s of that total. These historical measurements used the former uvx dispatcher.
Current dispatcher measurements are in `verification/codex-hooks-20261002.md`.

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
plugin components. The dispatcher uses `uv tool dir`, so `uv` must be available on `PATH`.
The first launch installs both storage drivers. Direct MCP startup reads the
same `~/.claude/methodology/backend.json` selection as the Claude launcher
before loading memory settings. `CORTEX_CLAUDE_DIR` relocates that shared
configuration root. Explicit `CORTEX_MEMORY_STORE_BACKEND`, then
`CORTEX_BACKEND`, then a non-empty `DATABASE_URL` or
`CORTEX_MEMORY_DATABASE_URL` take precedence over the saved selection.
The Codex hook entry uses the same store factory when no backend or URL is
configured. It selects the backend before running a hook, so automatic context
reads use the SQLite fallback that the MCP server selected on a fresh install.

Without a saved selection or explicit backend, Cortex keeps its existing
`auto` behavior: PostgreSQL first, then SQLite only when no explicit PostgreSQL
target was supplied and the default server is unavailable. An explicitly
configured but unreachable database URL remains an error rather than silently
redirecting writes. Both hosts must use the same configuration root and storage
settings to share memories; this does not merge previously separate stores.

Prepare the matching wheel with the native Python before restarting Codex:

```sh
python3 "<installed-plugin>/scripts/runtime.py" setup
```

This explicit setup is required for both MCP and lifecycle hooks. It installs
binary wheels into the uv tool environment. SessionEnd preserves failures in
its queue for later recovery. The MCP server retains its 180-second startup
ceiling; this includes server initialization, not dependency preparation.
The bundled MCP command is equivalent to:

```sh
env CORTEX_RUNTIME=cowork python3 "${PLUGIN_ROOT}/scripts/runtime.py" server
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
