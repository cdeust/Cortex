# Cortex documentation

This page sorts the existing documentation by the task you came to do. It holds
no facts of its own: every entry points at the one document that owns the
subject, so a correction is made once, where it belongs. The links and their
section anchors are checked by `tests_py/scripts/test_docs_index_links.py`.

## 1. First local memory round trip

1. Install the plugin: [README § Install](../README.md#install).
2. Check the environment before the first session:
   `python -m mcp_server.doctor` (one line per check, with the fix for each).
3. Store and retrieve one memory with the `remember` and `recall` tools:
   their schemas ([`remember`](api-reference.md#remember),
   [`recall`](api-reference.md#recall)), and what each
   call does inside ([write path](data-flow.md#memory-write-path-remember),
   [read path](data-flow.md#memory-read-path-recall)).
4. See where the memory now lives and how to delete it:
   [PRIVACY § Where your data is stored](../PRIVACY.md#where-your-data-is-stored) and
   [§ Your controls](../PRIVACY.md#your-controls).

Known problems on this path are tracked in the open: the host ignores the plugin's
`postInstall` step ([#703](https://github.com/cdeust/Cortex/issues/703)), a profile
with no configuration can reach for a local PostgreSQL
([#704](https://github.com/cdeust/Cortex/issues/704)), and the first SessionStart
downloads both model files inside the hook
([#705](https://github.com/cdeust/Cortex/issues/705)). Read
[Limits worth knowing before you install](../README.md#limits-worth-knowing-before-you-install)
first.

## 2. Concepts

- What Cortex keeps, checks and lets fade: [README § Keep context useful](../README.md#keep-context-useful).
- Storage backends, SQLite by default and PostgreSQL as an opt-in:
  [README § Storage](../README.md#storage).
- Layers and module boundaries: [architecture.md](architecture.md),
  [module-inventory.md](module-inventory.md).
- Every pipeline, step by step: [data-flow.md](data-flow.md).
- What the retrieval numbers do and do not establish:
  [README § Does the retrieval work](../README.md#does-the-retrieval-work),
  [README § Verification](../README.md#verification),
  [benchmarks-detail.md](benchmarks-detail.md).

## 3. Set up a host

- Claude Code and Codex: [README § Cortex in Codex and Claude Code](../README.md#cortex-in-codex-and-claude-code),
  [codex-plugin.md](codex-plugin.md).
- Claude and Codex on the same memory: [shared-host-memory.md](shared-host-memory.md).
- Claude Desktop, Cowork and other MCP hosts: [README § Every other MCP host](../README.md#every-other-mcp-host).
- The upstream MCP servers that `ingest_codebase` and `ingest_prd` consume:
  [mcp-connections.example.json](mcp-connections.example.json).
- Windows, WSL, dev containers, remote PostgreSQL, corporate proxies and headless CI:
  [deployment-scenarios.md](deployment-scenarios.md).
- Scheduled background grooming: [groomer-scheduling.md](groomer-scheduling.md).

## 4. API contracts

- Tool catalogue, by tier, with purpose and target latency: [mcp-tools.md](mcp-tools.md).
- Input schemas, responses and errors: [api-reference.md](api-reference.md),
  [error codes](api-reference.md#error-codes).
- Design decisions behind the contracts: [adr/](adr/).

## 5. Troubleshooting

- A codebase ingest that looks hung: [troubleshooting.md](troubleshooting.md), starting at
  [Is it hung or just slow?](troubleshooting.md#1-is-it-hung-or-just-slow).
- Setup errors: [troubleshooting.md § Common setup errors](troubleshooting.md#5-common-setup-errors).
- A model download that stalls behind a proxy:
  [troubleshooting.md § Stalled model download](troubleshooting.md#4-stalled-model-download),
  [deployment-scenarios.md § Corporate proxy](deployment-scenarios.md#corporate-proxy--custom-ca-model-downloads).
- Local log files and their rotation: [runbooks/local-log-rotation.md](runbooks/local-log-rotation.md).

## 6. Privacy, security and costs

- What is processed, where it is stored and what leaves the machine: [PRIVACY.md](../PRIVACY.md),
  in particular [What leaves your machine](../PRIVACY.md#what-leaves-your-machine).
- What Cortex can reach and how to report a vulnerability: [SECURITY.md](../SECURITY.md),
  and the argument with its evidence: [ASSURANCE-CASE.md](ASSURANCE-CASE.md).
- Energy and carbon: no figure is published, and the page says why:
  [README § Green software engineering](../README.md#green-software-engineering).

## 7. Contributing

- The gates a change has to clear: [CONTRIBUTING.md](../CONTRIBUTING.md),
  [testing-guide.md](testing-guide.md).
- Who decides and where the project is going: [GOVERNANCE.md](../GOVERNANCE.md),
  [ROADMAP.md](ROADMAP.md).
