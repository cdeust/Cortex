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
  Keep decisions, fixes and project context between sessions, and inspect what was retrieved.<br>
  Runs locally by default. No account, no API key, no server to manage.
</p>

<p align="center">
  <sub><em><strong>Independent project:</strong> Cortex is an independent, open-source project. It is <strong>not an Anthropic product</strong> and is not affiliated with, sponsored by, or endorsed by Anthropic.</em></sub>
</p>

---

**Sovereign is what it is today.** Everything runs on your machine: a local SQLite file by
default, or PostgreSQL + pgvector if you prefer. No LLM in the retrieval loop, and nothing
leaves localhost unless you configure an integration that does. Your project's memory is a
file you own and can delete.

**Cross-platform is how it is built.** One stdio MCP server, the same 52 tools on Claude Code,
Claude Desktop, Claude Cowork, Codex, ChatGPT desktop, Gemini CLI, Cursor, Windsurf and VS
Code. What differs per host is stated in a table below, not discovered after install.

**Eco-responsible is what we are aiming at.** Work that never reaches a datacenter is work
nobody has to power, and an agent that finds the right context first time re-reads fewer
files. We hold that intent to the
[Green Software Foundation's SCI method](https://sci.greensoftware.foundation/), and we
publish **no CO₂ or energy figure**, because we have not measured one.
[What we do and do not claim ↓](#green-software-engineering)

> **36 neuroscience mechanisms · 52 memory tools · 9 lifecycle hooks · a self-curating per-project wiki — all local, all open-source, MIT.**

## Install

**Claude Code** — add the marketplace and install the plugin:

```bash
claude plugin marketplace add cdeust/Cortex
claude plugin install hypermnesia-mcp
```

**Claude Desktop** — download `hypermnesia-mcp.mcpb` from
[Releases](https://github.com/cdeust/Cortex/releases) and open it, or use
**Settings → Extensions**. The bundle carries the tools but no hooks; the MCPB format has none.

**Claude Cowork** is detected automatically (`CLAUDE_ENVIRONMENT=cowork`) and uses the local
SQLite store. No PostgreSQL required.

**Any other stdio MCP host** (Codex, Gemini CLI, Cursor, Windsurf, VS Code) launches the same
server and gets the same tools. The per-host matrix and launch commands are in
[Every other MCP host](#every-other-mcp-host) below. Codex has a native package:
[docs/codex-plugin.md](docs/codex-plugin.md). WSL, TLS client certificates and corporate
proxies are covered in [docs/deployment-scenarios.md](docs/deployment-scenarios.md).

The first use creates a local SQLite store under `~/.claude/methodology/`. Models are downloaded
once when needed and then run offline. The embedding and reranking model files are both fetched
on first use. Optional integrations, remote PostgreSQL, and OTLP telemetry use the network only
when explicitly configured. [PRIVACY.md](PRIVACY.md) lists the exact scope.

An existing PostgreSQL install is never silently downgraded: the installer detects a
configured `DATABASE_URL`, a prior backend marker, or a reachable local `cortex` database and
keeps it across updates.

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

## Keep context useful

Across sessions, agents need to remember decisions, bring prior fixes back when a similar problem
returns, and show you which sources support a memory so you can correct it. Cortex keeps that
context available while making its status visible.

Cortex does this with local quality checks: what is written, whether its references resolve, what
happens when a decision changes, and what can fade over time.

### What gets in

A write passes a local novelty check (the implementation calls it a predictive-coding gate) against
what is already stored. Novel content is written; a near-duplicate is merged into the memory it
restates rather than filed beside it.

```js
// Illustrative project decision:
remember({ content: "Keep session state in Redis so TTL expiry is handled consistently." })
// → { stored: true, action: "stored" }
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

That memory named a file that no longer existed, so it was stored and labelled `unverifiable`
instead of being silently presented as verified. Rewritten against paths that resolve, the same
memory grades `verified`. A recalled memory tells you which kind it is; a `verified` grade still
means that the references resolve locally, not that the claim has been independently proven true.

### When it turns out wrong

Corrections supersede rather than overwrite. The new memory records what it replaces, the old
one is demoted in recall, and the chain stays readable.

```js
remember({ content: "...", supersedes_id: 4360411 })
// → { action: "superseded", memory_id: 4360412, superseded_id: 4360411 }
```

### What fades

Memories carry heat that decays unless replay reinforces them, and episodic traces can consolidate
into semantic ones. A specific debugging session may compress to the principle it taught; the
commands can fade while the lesson survives. This lifecycle is designed to keep the store useful
as it grows, though it is not a promise of a fixed size or guaranteed semantic compression.

## What it feels like in use

Here is an illustrative workflow: decisions, prior fixes, and source checks becoming useful again.

**Monday.** An hour debugging a webhook handler ends in a race condition: TTL expiry firing
between the auth check and the permission lookup. You agree on a fix, implement it, close the
session.

**Thursday.** In another session, a user reports intermittent logouts. Cortex surfaces relevant
prior analysis, the Redis decision, and the TTL lesson when their content matches the new work.

**Three weeks later.** The sessions can consolidate into a pattern about authentication and
TTL-based caches; some details may fade while the principle remains useful.

In Claude Code that is automatic: nine lifecycle hooks inject context at session start, recall
per prompt, capture as you work, checkpoint before compaction, and run a per-project wiki that
curates itself. In any other stdio MCP host you call the same 52 tools yourself, or 55 when
the optional `ai-architect-mcp-codebase` and `ai-architect-mcp-spec` integrations are present.

## Does the retrieval work

Measured against a published benchmark, retrieval only. No LLM reader in the loop: the
question is whether the right memory surfaces, not whether a model can write a good answer
from it.

**LongMemEval**: 500 human-curated questions buried in about 40 sessions of history.

| Historical Cortex run (v4.14.1) | Result |
|---|---|
| Recall@10 | **98.2%** |
| MRR | **0.9167** |

Historical single run from v4.14.1, not a v4.20.0 performance result: n=500, clean database,
consolidation disabled. [Artifact JSON](benchmarks/results/repro/20260714-v4.14.1-pretag/longmemeval-s.json);
[code SHA](https://github.com/cdeust/Cortex/commit/28145f0b7a113fc06e22568de6feea7f8444eaf5).
Reproduce with `benchmarks/reproduce.sh`, which runs in an isolated ephemeral container, never
against a live store.

Recall@10 is the share of questions whose answer-bearing session appears in the first ten
retrieved sessions. MRR (mean reciprocal rank) rewards finding that session near the top. These
numbers describe retrieval only; they do not measure whether an LLM writes a correct answer.

Retrieval fuses five signals through weighted reciprocal-rank fusion, then reranks with a
cross-encoder: vector similarity, full-text search, trigram match, heat and recency. LoCoMo
and BEAM results, the ablations and the floor gates are in [benchmarks/](benchmarks/).

## Storage

SQLite by default. PostgreSQL is one configuration field, worth it for very large stores or a
database shared across a team.

```bash
bash <plugin-dir>/scripts/install-plugin.sh --postgres
```

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

## Every other MCP host

The server is host-agnostic. Any host that can launch a stdio process gets the full tool
surface on the default SQLite store. What is not portable are the nine lifecycle hooks, which
are Claude Code plugin machinery; the server never imports or requires them at startup.

| Capability | Claude Code plugin | Local stdio hosts (Gemini CLI, Codex CLI, ChatGPT desktop, Cursor, Windsurf, VS Code, Agents SDK) | ChatGPT web |
|---|---|---|---|
| All 52 memory tools (`remember`, `recall`, wiki, navigation, consolidation, triggers, rules) | ✅ | ✅ | ❌ no remote HTTPS endpoint is shipped |
| SQLite default store / PostgreSQL opt-in | ✅ | ✅ | ❌ would need a remote deployment and a per-user storage and auth model |
| Auto-capture of significant tool output | ✅ PostToolUse hook | ❌ store explicitly with `remember` | ❌ |
| Session-start context injection | ✅ SessionStart hook | ❌ call `recall` yourself | ❌ |
| Per-prompt auto-recall | ✅ | ❌ | ❌ |
| Compaction checkpoints | ✅ | ❌ | ❌ |
| Autonomous wiki cycle | ✅ | ❌ run `consolidate` / `curate_wiki` manually | ❌ |
| Cognitive profiling (`query_methodology`) | ✅ | ⚠️ profiles are mined from Claude Code session logs under `~/.claude/`; without them the profile is empty | ❌ |

On Claude Code memory is ambient: hooks capture and inject automatically. On every other host
memory is tool-driven: the agent stores and retrieves when instructed, and nothing happens
between prompts.

The launch command on every host is the PyPI package. The `[sqlite]` extra enables
sqlite-vec vector search; without it the store still works, with vector search disabled.

```bash
uvx --from "hypermnesia-mcp[sqlite]" hypermnesia-mcp
```

**Gemini CLI** ships as an extension (`gemini-extension.json` is in this repository):

```bash
gemini extensions install https://github.com/cdeust/Cortex
```

**Codex and ChatGPT desktop** have a native plugin with a 10-tool lean surface. Pre-install
the package once so the plugin's first `uvx` handshake reuses the local uv cache instead of
spending its startup budget downloading a Python environment:

```bash
uv tool install "hypermnesia-mcp[sqlite]"
codex plugin marketplace add cdeust/Cortex
codex plugin add hypermnesia-mcp-codex@cortex-codex-plugins
```

The direct fallback registers the executable without the plugin:

```bash
codex mcp add cortex --env CORTEX_MEMORY_STORE_BACKEND=sqlite -- hypermnesia-mcp
```

The host boundary, the measured startup ceiling and the public-directory requirements Cortex
deliberately does not claim are in [docs/codex-plugin.md](docs/codex-plugin.md).

## Green software engineering

Cortex runs a standing efficiency programme, gated by the same evidence rule as the retrieval
work: **no unsourced efficiency claim ships.** Waste is treated as a defect with a
reproduction, not as a virtue to advertise.

### The measurement harness, and what it does not establish

`benchmarks/energy/` implements the
[Green Software Foundation SCI specification](https://sci.greensoftware.foundation/):
operational emissions `O = E × I`, embodied allocation `M = TE × TS × RS`, reported per
functional unit. For the embedding path the functional unit is **1000 model input tokens**,
counted from the tokenizer's own `attention_mask`, never estimated from characters.

Read [benchmarks/energy/README.md](benchmarks/energy/README.md) before quoting anything from
it. Its first paragraph is the important one: the automated fixtures exercise arithmetic and
failure paths, they **do not measure device energy and do not establish an energy
improvement.** By design:

- **No default carbon factors.** `--carbon-intensity` (gCO2eq/kWh) and `--embodied`
  (gCO2eq/s, an already allocated rate) are mandatory operator inputs, validated before any
  model import. The harness records the values and their units; it does not vouch for their
  provenance.
- **A stated boundary.** `raw_system_energy_j` is the sensor's combined CPU+GPU+ANE estimate.
  It is neither wall-plug energy nor a complete device SCI score: memory, storage, screen,
  power-supply losses, model warm-up and token counting are all excluded.
- **Artifacts or it did not happen.** A successful run preserves `results.json`, a
  `MANIFEST.json` of commit and source hashes, and the exact analyzed `powermetrics.txt`
  snapshot.

No energy results are committed to this repository. A figure measured on one operator's
machine, region and duty cycle is not a property of the software, and publishing it as one
would be the drift this programme exists to prevent.

### What has actually shipped

Efficiency work lands as ordinary reviewed PRs.

| Workstream | Change | PR |
|---|---|---|
| **CI / build** | run pytest once, on the coverage leg, instead of twice | [#475](https://github.com/cdeust/Cortex/pull/475) |
| | build runtime images only on Docker changes, plus a weekly validation | [#476](https://github.com/cdeust/Cortex/pull/476) |
| | cache pinned dependency and actionlint downloads | [#477](https://github.com/cdeust/Cortex/pull/477) |
| | sdist under 5 MB, with a byte-identical wheel | [#478](https://github.com/cdeust/Cortex/pull/478) |
| | measured job timeouts; cancel superseded PR runs | [#479](https://github.com/cdeust/Cortex/pull/479) |
| | bound the local Docker build context | [#481](https://github.com/cdeust/Cortex/pull/481) |
| | stop exporting an unreadable layer cache on every PR run | [#506](https://github.com/cdeust/Cortex/pull/506) |
| **Runtime** | defer unused pipeline hook imports | [#482](https://github.com/cdeust/Cortex/pull/482) |
| | route PostToolUse hooks by the tool names they handle | [#483](https://github.com/cdeust/Cortex/pull/483) |
| | audit and clean orphan plugin dependencies | [#484](https://github.com/cdeust/Cortex/pull/484) |
| | rotate telemetry and detached-worker logs | [#485](https://github.com/cdeust/Cortex/pull/485) |
| | persist hook cascade cadence; cool down misses | [#486](https://github.com/cdeust/Cortex/pull/486) |
| | pinned CPU-only Torch on Linux, no CUDA payload pulled | [#487](https://github.com/cdeust/Cortex/pull/487) |

The hook work is the load-bearing one, because hooks run on every tool event. Deferring the
handler/store stack keeps hook boot at **~0.05 s** against **~0.6 s** for the full registry
import (measured 2026-07-28; the constant is cited in `mcp_server/hooks/auto_recall.py` at its
call sites, per the no-invented-constants rule).

### Demand reduction is the primary lever

The largest efficiency term in an LLM-assisted workflow is not this server's own CPU. It is
the tokens a model must process because the right context was not found the first time. That
makes retrieval quality an energy property, and it is why the benchmark table above and this
section are the same programme: `response_budget.py` bounds a payload and keeps ids so
truncation stays resumable, the reranker degrades to first-stage scores rather than fetching
a model, and `CORTEX_RERANKER_OFFLINE=1` refuses the download outright.

## Under the hood

The mechanisms above are implemented as 36 system mechanisms spanning encoding, consolidation,
retrieval and forgetting. Each is cited to published work and exposed as a live system vital. The
[bibliography](docs/papers/bibliography.md) is
the check: its entry count is what the references badge reports, and a gate fails the build if
the two disagree.

Clean Architecture, concentric layers: `server → handlers → core ← shared`, and
`infrastructure → shared`. Core is pure and testable without mocks.
[docs/agent-guidance.md](docs/agent-guidance.md) is the map;
[docs/mcp-tools.md](docs/mcp-tools.md) is the tool reference.

## Limits worth knowing before you install

- The automatic behaviour is Claude Code plugin machinery. Elsewhere you call the tools
  yourself, and the host table above says exactly what is missing where.
- SQLite fusion is in-process and unindexed. Fine at personal scale, slower at very large one.
- The retrieval scores above are retrieval-only. They say nothing about answer quality.
- Provenance grading is local and structural. It checks that a reference resolves, not that a
  claim is true; a DOI or arXiv link is never auto-verified.
- No energy or carbon figure is published, for the reasons stated above.
- First use downloads both the embedding and reranking model files. Optional integrations, remote
  PostgreSQL and OTLP telemetry add network activity only when explicitly configured; see
  [PRIVACY.md](PRIVACY.md).

## Privacy Policy

Cortex is **local-first**: your memories, conversations and profiles stay on your machine,
stored in a local SQLite database (`~/.claude/methodology/memory.db`) by default, or in a
PostgreSQL database you control. Cortex sends **no** memories, content or telemetry to the
author, to Anthropic, or to any third party. The only outbound network activity is a one-time
download of open-source embedding and reranking models from Hugging Face (model files only),
plus any integrations you explicitly configure. The optional
[hypermnesia-mcp-viz](https://github.com/cdeust/cortex-viz) companion binds its server to
127.0.0.1. SafeSkill scan: **94/100** (code 97, content 88,
[docs/safeskill-report.json](docs/safeskill-report.json)). Full policy:
**[PRIVACY.md](PRIVACY.md)**.

## Support

- **Issues and bug reports:** [GitHub Issues](https://github.com/cdeust/Cortex/issues)
- **Security disclosures:** see [SECURITY.md](SECURITY.md)
- **Contact:** [admin@ai-architect.tools](mailto:admin@ai-architect.tools)

## Development

```bash
pytest                                # full suite; assets/badge-tests.svg carries the current count
ruff check . && ruff format --check . # lint and format, both enforced in CI
python scripts/check_doc_claims.py    # advertised counts must match the repo
python scripts/check_craftsmanship.py # file and method caps, layer whitelist, sourced constants
```

[CONTRIBUTING.md](CONTRIBUTING.md) describes the gates a change has to clear.
[GOVERNANCE.md](GOVERNANCE.md) says who decides and what happens if the maintainer stops.
[docs/ROADMAP.md](docs/ROADMAP.md) says where the project is going, and
[docs/ASSURANCE-CASE.md](docs/ASSURANCE-CASE.md) states the security argument and its limits.
[CHANGELOG.md](CHANGELOG.md) is the complete release history.

## License

MIT, see [LICENSE](LICENSE).

This software is the independent work of Clément Deust. It was developed outside any
employment relationship and is not affiliated with, endorsed by, or owned by any past or
present employer. It is part of the ai-architect ecosystem
([zetetic-team-subagents](https://github.com/cdeust/zetetic-team-subagents),
[ai-architect-mcp-codebase](https://github.com/cdeust/ai-architect-mcp-codebase),
[ai-architect-mcp-spec](https://github.com/cdeust/ai-architect-mcp-spec)).

The neuroscience and information-retrieval algorithms encoded in this software are derived
from published academic work cited in
[`docs/papers/bibliography.md`](docs/papers/bibliography.md) and inline in the source via
`# source:` annotations (Friston on predictive coding, Anderson & Lebiere on rate-distortion
forgetting, Nader et al. on retrieval-induced lability, McClelland et al. on consolidation,
and others). The MIT license covers this implementation; it does not assert ownership over
the underlying mechanisms, which remain attributable to their original authors and
publications.

## Citation

The paper PDFs on `main` are the canonical artefacts (arXiv IDs forthcoming, endorsement in
progress):

```bibtex
@software{cortex2026,
  title={Cortex: Persistent Memory for Claude Code},
  author={Deust, Clement},
  year={2026},
  url={https://github.com/cdeust/Cortex}
}

@unpublished{deust2026thermodynamic,
  title={Thermodynamic Memory vs. Flat-Importance Stores:
         Why Long-Term Retrieval Collapses Without Decay},
  author={Deust, Clement},
  year={2026},
  note={arXiv ID forthcoming, endorsement in progress},
  url={https://github.com/cdeust/Cortex/blob/main/docs/arxiv-thermodynamic/main.pdf}
}

@unpublished{deust2026context,
  title={Stage-Aware Context Assembly for Long-Context Memory Retrieval},
  author={Deust, Clement},
  year={2026},
  note={arXiv ID forthcoming, endorsement in progress},
  url={https://github.com/cdeust/Cortex/blob/main/docs/arxiv-context-assembly/main.pdf}
}
```
