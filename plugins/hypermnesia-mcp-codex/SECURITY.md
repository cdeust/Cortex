# Security Policy, Cortex plugin for Codex

This package is the Codex distribution of Cortex (`hypermnesia-mcp`). It
starts the published PyPI server over local stdio with the default `full` tool
profile and installs 11 lifecycle hooks. It ships no skills, apps or
agents, declares no remote endpoint and holds no secrets.

Read the two sections below before installing: the full profile and the hooks
are both wider than a read-only integration, and that is deliberate.

The security policy, supply-chain assurance (Sigstore build provenance, PEP 740
attestations, SBOM) and coordinated-disclosure process are shared with the
whole repository and live in the top-level
[SECURITY.md](https://github.com/cdeust/Cortex/blob/main/SECURITY.md).

## Reporting a vulnerability

Do not open a public issue. Send a private report through a
[GitHub security advisory](https://github.com/cdeust/Cortex/security/advisories/new).

## Tool surface

The server runs the default `full` profile, the same surface the Claude Code
plugin serves. That includes the profiling, curation, ingestion and
destructive-maintenance tools: `forget` and the `wiki_purge`/`wiki_migrate`
class, which delete or rewrite stored memory. Under the `lean` profile this
package used to ship, those were hidden from `tools/list` and rejected on
call; under `full` they are advertised and callable. They act on the local
memory store described below, not on your repository's files.

To run the reduced surface instead, override the server command with
`--profile lean`, or set `CORTEX_MCP_PROFILE=lean` in the server environment.

## Lifecycle hooks

`hooks/hooks.json` registers the 11 lifecycle hook modules on session, prompt,
tool and compaction events. Runtime hooks use the wheel version pinned to the
plugin. Session-end intake and recovery use a bundled Python standard-library
script. The hooks with effects beyond writing to the memory store:

- `decision_gate` and `no_deps_gate` run on `PreToolUse` for edits. They read
  the target file, and for an `apply_patch` call they read each patched file's
  current contents to compute what the edit would produce. They can **block
  the tool call** by exiting non-zero.
- `post_tool_capture` runs on every `PostToolUse` event and stores significant
  tool output as memory, so tool results are persisted locally by default.
- Session-end intake persists the event and storage selection in a private local
  queue, then **spawns a detached worker**. The worker runs `session_lifecycle`
  to update session/profile records and launch consolidation. Startup recovers
  pending jobs. Queue files and completion receipts stay under the configured
  Cortex methodology directory.
- `agent_briefing` injects scoped project/role context into native children and
  can append task-relevant memory to plaintext spawn arguments. Opaque
  collaboration arguments remain unchanged.
- `preemptive_context` parses supported shell file-access cues without executing
  shell text and boosts matching current memories within project/global scope.
- `post_commit_reindex` runs on shell events and may reindex the working
  repository into the local store.

One edit fires up to five of these processes (two before the call, three
after), so every `apply_patch` starts subprocesses that read files and write
to the memory store. Timings and the exact set are in
[docs/codex-plugin.md](https://github.com/cdeust/Cortex/blob/main/docs/codex-plugin.md).

Remove `"hooks": "./hooks/hooks.json"` from `.codex-plugin/plugin.json`, or
disable the plugin's hooks in Codex, to run the MCP server alone.

## What this package accesses

- The local memory store: PostgreSQL at `DATABASE_URL` when configured,
  otherwise the zero-config SQLite file under `~/.claude/methodology/`
  (see [PRIVACY.md](https://github.com/cdeust/Cortex/blob/main/PRIVACY.md)).
- Files referenced by the events the hooks receive, read-only, as described
  above. No hook writes to your repository.
- The `uvx` cache, used for server and runtime-hook startup. The package
  requirement is pinned to the installed plugin version. Intake does not wait
  for package startup before persisting the session-end event.

Nothing leaves the machine except the one-time model download described in
PRIVACY.md.
