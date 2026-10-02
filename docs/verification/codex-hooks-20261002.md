# Codex hooks repair — 2 October 2026

Source baseline: c32a6a025319407630cab4733a4e0b17ae2d9588, local edits only.
Host: macOS ARM, Codex CLI 0.160.0; desktop binary 0.159.0.

## Confirmed failure

All 28 original hooks were enabled and trusted according to native `hooks/list`.
The screenshot supplied by the owner shows repeated deadlines of 5/10 seconds
and exit code 1. Running the exact Cortex uvx command reproduced compilation of
cryptography50.0.2 for x86_64 on an aarch64 host. The compile failed because the
Intel Rust target and cross-compilation OpenSSL configuration were absent.
Installing the ARM uv tool alone did not change unqualified uvx selection.

## Local changes

The plugin dispatcher now validates the installed wheel version and launches its
isolated Python. Hooks, SessionEnd replay and MCP startup do not resolve packages.
Setup explicitly installs binary wheels with its native Python. The standalone
MCP configuration uses the same prepared Python; its previous pin was4.23.4
while installed hooks used4.23.5. Backend environment remains PostgreSQL.
Published runtime metadata now contains the Intel cryptography<49 bound already
documented by ADR-1092; no package, version or source changed in uv.lock.

## Verification

136 targeted tests pass (130 lifecycle/runtime tests, three documentation
contracts, two CI contracts and one telemetry regression): manifest contracts, runtime version checks, isolated
server/hook arguments, interruption recovery and concurrent queue deduplication,
plus published platform bounds. Ruff, craftsmanship and git diff --check pass.
Direct event probes return0: post_tool_capture1.148s, preemptive_context0.628s,
post_commit_reindex0.424s. Capture reports persistence pending; these exit codes
do not prove memory was committed. MCP initialization3.073s, tools/list59 tools;
query_methodology returns successfully through the restored local MCP server.
Recall exceeded both the initial 30-second diagnostic budget and a subsequent
20-second official-client budget while loading the embedding model; tool latency
remains unverified. These probes do not establish a recall regression. Owned
diagnostic servers were stopped.

Full installed SessionStart now returns0 in two consecutive probes:7.302s
and1.057s, emitting3128/3131bytes without printing memory content. Its connection
disables JIT locally, the grooming query uses the existing tags index, and the
banner checks distribution metadata without importing Torch/SciPy. See
[captured query evidence](codex-session-start-query-20261002.md). These are direct
manual probes, not native lifecycle delivery evidence. Cache/load conditions
differ; the measurements do not establish a guaranteed latency.

Native hooks/list after explicit owner approval:28 definitions, all28 trusted,
no parsing errors in Transartica, Cortex, Session Optimizer and Zetetic.
Native app-server notifications from two fresh threads confirm Cortex
SessionStart1.467/1.709s, UserPromptSubmit0.322/0.333s, three matching
PostToolUse handlers0.183–0.334s and SessionEnd0.102/0.107s all completed.
The command probe was a real model-issued printf, followed by thread/archive.
The two captures also found invalid SessionStart JSON from disk-hygiene and
statusline; those are separate plugin repairs and prevent claiming the whole
installation has zero hook errors. PreCompact, edit gates and subagent events
were not triggered in these cycles and remain unverified natively.

The first native trust-all attempt was rejected by automatic approval review.
The owner subsequently approved the exact11Hypermnesia hooks; approval was
applied through Codex /hooks, then verified across the four repositories.
No trust hashes were rewritten outside the native interface.

This report precedes PR publication. No release, database migration or deletion
of shared caches was performed.
Concurrent untracked work remains untouched. Old installed definitions and
config are preserved in ~/.codex/backups for review/recovery.
