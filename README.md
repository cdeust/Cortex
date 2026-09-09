<!-- mcp-name: io.github.cdeust/hypermnesia-mcp -->

<p align="center">
  <img src="assets/banner.svg" alt="Cortex — cross-platform persistent memory for AI coding agents" width="820">
</p>

<p align="center">
  <a href="https://github.com/cdeust/Cortex/actions/workflows/ci.yml"><img src="https://github.com/cdeust/Cortex/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="LICENSE"><img src="assets/badge-license.svg" alt="License: MIT"></a>
  <img src="assets/badge-python.svg" alt="Python 3.10+">
  <img src="assets/badge-tests.svg" alt="tests passing">
  <img src="assets/badge-references.svg" alt="97 referenced papers">
  <img src="assets/badge-version.svg" alt="Version 4.20.0">
  <a href="https://www.bestpractices.dev/projects/13836"><img src="https://www.bestpractices.dev/projects/13836/badge" alt="OpenSSF Best Practices"></a>
  <a href="https://mcptoplist.com/server/io.github.cdeust%2Fhypermnesia-mcp"><img src="assets/badge-mcp-toplist.svg" alt="MCP Toplist: Top 1.2% of 81,919 tracked MCP servers, July 2026"></a>
</p>

<p align="center">
  <strong>Give your AI coding agent a memory that survives the session.</strong><br>
  Runs entirely on your machine. No account, no API key, no server.
</p>

---

## Why

Your agent solves a problem, you close the session, and the solution is gone. Next week you
debug the same thing, re-explain the same architecture, re-litigate the same decision.

Cortex stores what happened and brings it back when it is relevant. In Claude Code that is
automatic: decisions and fixes are captured as you work and injected at the start of the next
session. In any other stdio MCP host you call the same tools yourself.

## Install

**Claude Code**

```bash
claude plugin marketplace add cdeust/Cortex
claude plugin install hypermnesia-mcp
```

**Claude Desktop** — download `hypermnesia-mcp.mcpb` from
[Releases](https://github.com/cdeust/Cortex/releases) and open it, or use
**Settings → Extensions**.

**Any other stdio MCP host** (Codex, Gemini CLI, Cursor, Windsurf, VS Code) launches the same
server and gets the same tools. Codex has a native package:
[docs/codex-plugin.md](docs/codex-plugin.md). WSL, TLS client certificates and corporate
proxies are covered in [docs/deployment-scenarios.md](docs/deployment-scenarios.md).

That is the whole install. It runs on a local SQLite file under `~/.claude/methodology/`,
with no database to provision. The embedding model is not downloaded at install time; it
fetches once on first use (about 100 MB) and runs offline afterwards. See
[PRIVACY.md](PRIVACY.md) for exactly what touches the network.

<details>
<summary><strong>Upgrading from an older plugin identity</strong></summary>

The plugin was renamed `hypermnesia-mcp` in v4.15.0, after a community-directory collision
with an unrelated `cortex` plugin. Memories, configuration and storage paths are untouched.

```bash
claude plugin uninstall cortex
claude plugin install hypermnesia-mcp
```

The visualization companion, <a href="https://github.com/cdeust/cortex-viz">hypermnesia-mcp-viz</a>,
was renamed the same way:

```bash
claude plugin uninstall cortex-viz@cortex-plugins
claude plugin marketplace update cortex-plugins
claude plugin install hypermnesia-mcp-viz@cortex-plugins
```

The retained `cortex-viz@cortex-plugins` entry is a frozen shim that only prints this notice
and exposes no server or tools.

Allowlists, hooks, skills and agents must migrate both composed tool names:
`mcp__plugin_cortex-viz_cortex-viz__open_visualization` becomes
`mcp__plugin_hypermnesia-mcp-viz_hypermnesia-mcp-viz__open_visualization`, and
`mcp__plugin_cortex-viz_cortex-viz__get_methodology_graph` becomes
`mcp__plugin_hypermnesia-mcp-viz_hypermnesia-mcp-viz__get_methodology_graph`.

</details>

## What you get

**Automatic, in Claude Code.** Nine lifecycle hooks do the work you would otherwise have to
remember to do: context injected at session start, relevant memories recalled per prompt,
decisions and fixes captured as you work, a checkpoint written before compaction, and a
per-project wiki that curates itself.

**On demand, everywhere.** 52 memory tools (55 when the optional `ai-architect-mcp-codebase`
and `ai-architect-mcp-spec` integrations are installed):
`remember` and `recall`, wiki authoring, graph navigation, consolidation, triggers and rules.
The hooks are Claude Code plugin machinery; the tools are not, and the server never requires
them to start.

## Does the retrieval actually work

Measured against published benchmarks, retrieval only. No LLM reader in the evaluation loop:
we measure whether the right memory surfaces, not whether a model can write a good answer
from it.

**LongMemEval** (Wu et al., ICLR 2025). 500 human-curated questions buried in about 40
sessions of history. The paper's best retrieval reached 78.4% Recall@10.

| | Cortex |
|---|---|
| Recall@10 | **98.2%** |
| MRR | **0.9167** |

<sub>n=500, clean-database run, `benchmarks/results/repro/20260714-v4.14.1-pretag/longmemeval-s.json`,
code SHA `28145f0b7a113fc06e22568de6feea7f8444eaf5`. Reproduce with `benchmarks/reproduce.sh`,
which runs in an isolated ephemeral container, never against a live store.</sub>

Retrieval fuses five signals through weighted reciprocal-rank fusion, then reranks with a
cross-encoder: vector similarity, full-text search, trigram match, heat and recency. LoCoMo
and BEAM results, the ablations, and the floor gates live in
[benchmarks/](benchmarks/).

## Storage

SQLite by default. PostgreSQL is a single configuration field, worth it for very large stores
or a database shared across a team.

```bash
bash <plugin-dir>/scripts/install-plugin.sh --postgres
```

An existing PostgreSQL install is never silently downgraded: the installer detects a
configured `DATABASE_URL`, a prior backend marker, or a reachable local `cortex` database and
keeps it across updates.

|  | SQLite (default) | PostgreSQL 15+ |
|---|---|---|
| Setup | none | pgvector, pg_trgm |
| All 52 tools | yes | yes |
| Retrieval contract | identical | identical |
| Fusion | in-process | server-side PL/pgSQL |
| ANN index | none | pgvector HNSW |
| Cross-agent team decisions, preemptive context, pipeline heat bumps | no-op | active |

The honest version of that last row: three hook enrichments are PostgreSQL-only and degrade
to silent no-ops on SQLite. Session banners, auto-recall, auto-capture, checkpoints and every
memory tool work on both.

## Under the hood

Memory is modelled on how memory is understood to work, not on a vector store with a
timestamp: 36 mechanisms spanning encoding, consolidation, retrieval and forgetting, each
cited to published work and exposed as a live system vital. Writes pass a predictive-coding
novelty gate, memories decay thermodynamically unless replayed, and episodic traces
consolidate into semantic ones the way complementary learning systems describe.

If that sounds like decoration, the [bibliography](docs/papers/bibliography.md) is the check.
Its entry count is what the references badge above reports, and a gate fails the build if the
two disagree.

Clean Architecture, concentric layers: `server → handlers → core ← shared`, and
`infrastructure → shared`. Core is pure and testable without mocks. See
[docs/agent-guidance.md](docs/agent-guidance.md) for the map.

## Limits worth knowing before you install

- The Claude Code plugin is where the automatic behaviour lives. Elsewhere you call the tools
  yourself, and the `.mcpb` bundle carries no hooks because the format has none.
- SQLite fusion is in-process and unindexed. Fine at personal scale, slower at very large one.
- Retrieval scores above are retrieval-only. They say nothing about answer quality.
- The embedding model download is the one network call at first use.

## Project

[CHANGELOG.md](CHANGELOG.md) · [PRIVACY.md](PRIVACY.md) · [CONTRIBUTING.md](CONTRIBUTING.md) ·
[SECURITY.md](SECURITY.md) · [benchmarks/](benchmarks/) · [docs/](docs/)

Python 3.10+. MIT licensed. Issues and pull requests welcome; CONTRIBUTING.md describes the
gates a change has to clear.
