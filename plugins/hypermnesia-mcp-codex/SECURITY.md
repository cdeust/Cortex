# Security Policy — Cortex plugin for Codex

This package is the Codex distribution of Cortex (`hypermnesia-mcp`). It
starts the published PyPI server over local stdio with the default `full` tool
profile and installs eleven lifecycle hooks. It ships no skills, apps or
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

`hooks/hooks.json` registers eleven commands that Codex runs on session,
prompt, tool and compaction events. Each is a separate
`uvx --from "hypermnesia-mcp[postgresql,sqlite]" hypermnesia-mcp-hook <module>`
process. The ones with effects beyond writing to the memory store:

- `decision_gate` and `no_deps_gate` run on `PreToolUse` for edits. They read
  the target file, and for an `apply_patch` call they read each patched file's
  current contents to compute what the edit would produce. They can **block
  the tool call** by exiting non-zero.
- `post_tool_capture` runs on every `PostToolUse` event and stores significant
  tool output as memory, so tool results are persisted locally by default.
- `session_lifecycle` runs at `SessionEnd` and **spawns a detached
  subprocess** that outlives the hook to run consolidation.
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
- The `uvx` cache, to resolve the pinned `hypermnesia-mcp` release on first
  launch, and on every hook invocation.

Nothing leaves the machine except the one-time model download described in
PRIVACY.md.
