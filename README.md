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
  <strong>Memory for AI coding agents that you can hold accountable.</strong><br>
  Runs entirely on your machine. No account, no API key, no server.
</p>

---

## The problem with agent memory

Storing everything is easy. Three months in, that is the problem: a store full of half-truths
from sessions where the agent was confidently wrong, stale decisions that were reversed, and
duplicates of the same fact worded five ways. Retrieval gets worse as the store grows, and
you cannot tell which memories to trust.

Cortex is built around the opposite constraint. Most of it is quality control: what is allowed
in, whether a memory can be checked, what happens when one turns out wrong, and what is
allowed to fade.

### What gets in

A write passes a predictive-coding gate that scores it against what is already stored. Novel
content is written; a near-duplicate is merged into the memory it restates rather than filed
beside it.

```js
remember({ content: "The installer must pass --no-deps: the constraint file is the complete uv-resolved closure." })
// → { stored: true, memory_id: 4360412, action: "stored",
//     novelty: { embedding: 0.23, entity: 0.11, structural: 0.33 } }
```

Deliberate writes are never rejected for being unsurprising. Unattended capture is, which is
what keeps automatic capture from burying the memories you meant to keep.

### Whether it can be checked

Every memory is graded at write time, locally, with no network call. The grade is not a
confidence score: it is whether the claims carry references that resolve on this machine.

```js
// → provenance: { grade: "unverifiable",
//                 reason: "dead_refs: deps/numpy/_core/_multiarray_umath.cpython-313-darwin.so",
//                 hint: "1 of 9 checkable reference(s) could not be resolved" }
```

That memory named a file that no longer existed, so it was stored and graded honestly instead
of being returned later as fact. Rewritten against paths that resolve, the same memory grades
`verified`. A recalled memory tells you which kind it is.

### When it turns out wrong

Corrections supersede rather than overwrite. The new memory records what it replaces, the old
one is demoted in recall, and the chain stays readable.

```js
remember({ content: "...", supersedes_id: 4360411 })
// → { action: "superseded", memory_id: 4360412, superseded_id: 4360411 }
```

### What fades

Memories carry heat that decays unless replay reinforces them, and episodic traces consolidate
into semantic ones. A specific debugging session compresses to the principle it taught; the
commands fade, the lesson survives. The store curates itself instead of growing without bound.

## What it feels like in use

**Monday.** An hour debugging a webhook handler ends in a race condition: TTL expiry firing
between the auth check and the permission lookup. You agree on a fix, implement it, close the
session.

**Thursday.** Different project, a user reports intermittent logouts. Before you have finished
describing the bug, Cortex has surfaced Monday's analysis, the older decision to keep all
session state in Redis, and a lesson about TTL edge cases in distributed caches.

**Three weeks later.** Those sessions have consolidated into one pattern about authentication
and TTL-based caches. The Redis specifics are gone. The principle is what comes back.

In Claude Code that is automatic: nine lifecycle hooks inject context at session start, recall
per prompt, capture as you work, checkpoint before compaction, and run a per-project wiki that
curates itself. In any other stdio MCP host you call the same 52 tools yourself, or 55 when
the optional `ai-architect-mcp-codebase` and `ai-architect-mcp-spec` integrations are present.

## Install

**Claude Code**

```bash
claude plugin marketplace add cdeust/Cortex
claude plugin install hypermnesia-mcp
```

**Claude Desktop** — download `hypermnesia-mcp.mcpb` from
[Releases](https://github.com/cdeust/Cortex/releases) and open it, or use
**Settings → Extensions**. The bundle carries the tools but no hooks; the MCPB format has none.

**Any other stdio MCP host** (Codex, Gemini CLI, Cursor, Windsurf, VS Code) launches the same
server and gets the same tools. Codex has a native package:
[docs/codex-plugin.md](docs/codex-plugin.md). WSL, TLS client certificates and corporate
proxies are covered in [docs/deployment-scenarios.md](docs/deployment-scenarios.md).

It runs on a local SQLite file under `~/.claude/methodology/`, with no database to provision.
The embedding model is not downloaded at install time; it fetches once on first use, about
100 MB, and runs offline afterwards. [PRIVACY.md](PRIVACY.md) says exactly what touches the
network, and it is a short list.

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

## Does the retrieval work

Measured against a published benchmark, retrieval only. No LLM reader in the loop: the
question is whether the right memory surfaces, not whether a model can write a good answer
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
and BEAM results, the ablations and the floor gates are in [benchmarks/](benchmarks/).

## Storage

SQLite by default. PostgreSQL is one configuration field, worth it for very large stores or a
database shared across a team.

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

Three hook enrichments are PostgreSQL-only and degrade to silent no-ops on SQLite. Session
banners, auto-recall, auto-capture, checkpoints and every memory tool work on both.

## Under the hood

The mechanisms above are not metaphors borrowed from neuroscience after the fact. There are 36
of them spanning encoding, consolidation, retrieval and forgetting, each cited to published
work and exposed as a live system vital. The [bibliography](docs/papers/bibliography.md) is
the check: its entry count is what the references badge reports, and a gate fails the build if
the two disagree.

Clean Architecture, concentric layers: `server → handlers → core ← shared`, and
`infrastructure → shared`. Core is pure and testable without mocks.
[docs/agent-guidance.md](docs/agent-guidance.md) is the map;
[docs/mcp-tools.md](docs/mcp-tools.md) is the tool reference.

## Limits worth knowing before you install

- The automatic behaviour is Claude Code plugin machinery. Elsewhere you call the tools
  yourself.
- SQLite fusion is in-process and unindexed. Fine at personal scale, slower at very large one.
- The retrieval scores above are retrieval-only. They say nothing about answer quality.
- Provenance grading is local and structural. It checks that a reference resolves, not that a
  claim is true; a DOI or arXiv link is never auto-verified.
- The embedding model download is the one network call at first use.

## Project

[CHANGELOG.md](CHANGELOG.md) · [PRIVACY.md](PRIVACY.md) · [CONTRIBUTING.md](CONTRIBUTING.md) ·
[SECURITY.md](SECURITY.md) · [benchmarks/](benchmarks/) · [docs/](docs/)

Python 3.10+. MIT licensed. Issues and pull requests welcome; CONTRIBUTING.md describes the
gates a change has to clear.
