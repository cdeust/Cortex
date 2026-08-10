<!-- mcp-name: io.github.cdeust/hypermnesia-mcp -->

<p align="center">
  <img src="assets/banner.svg" alt="Cortex — cross-platform persistent memory for AI coding agents" width="820">
</p>

<p align="center">
  <a href="https://github.com/cdeust/Cortex/actions/workflows/ci.yml"><img src="https://github.com/cdeust/Cortex/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="LICENSE"><img src="assets/badge-license.svg" alt="License: MIT"></a>
  <img src="assets/badge-python.svg" alt="Python 3.10+">
  <img src="assets/badge-tests.svg" alt="tests passing">
  <img src="assets/badge-references.svg" alt="97 referenced papers">  <img src="assets/badge-version.svg" alt="Version 4.17.1">
  <a href="https://www.bestpractices.dev/projects/13836"><img src="https://www.bestpractices.dev/projects/13836/badge" alt="OpenSSF Best Practices"></a>
  <a href="https://mcptoplist.com/server/io.github.cdeust%2Fhypermnesia-mcp"><img src="assets/badge-mcp-toplist.svg" alt="MCP Toplist: Top 1.2% of 81,919 tracked MCP servers, July 2026"></a>
</p>

<p align="center">
  <strong>Cross-platform persistent memory for Codex, Gemini CLI, Claude Code, and other local MCP hosts — built on computational neuroscience, not just retrieval.</strong> 36 cited brain mechanisms consolidate what matters, keep it current as your project evolves, and reconstruct the right context at the right time. The MCP server is host-agnostic; Claude Code adds optional automatic lifecycle hooks.
</p>

<p align="center">
  <a href="#getting-started">Getting Started</a> · <a href="#configuration">Configuration</a> · <a href="#examples">Examples</a> · <a href="#whats-new">What's New</a> · <a href="#the-science-under-the-hood">Science</a> · <a href="#retrieval-that-actually-works">Benchmarks</a> · <a href="#the-autonomous-wiki">Wiki</a> · <a href="#architecture">Architecture</a>
</p>

<p align="center">
  <strong>Part of a four-piece stack</strong> — each runs standalone; together they cover what an agent forgets, can't see, and can't verify. <a href="#the-rest-of-the-stack">Full comparison ↓</a><br>
  <a href="https://github.com/cdeust/ai-architect-mcp-codebase">ai-architect-mcp-codebase</a> — the repo as a queryable code graph (callers, blast radius, execution paths), so agents stop re-reading files; Cortex ingests it via <code>ingest_codebase</code> / <code>change_impact</code><br>
  <a href="https://github.com/cdeust/ai-architect-mcp-spec">ai-architect-mcp-spec</a> — <em>verifies</em> a spec rather than only generating one; standalone, or a CI gate over spec-kit / Kiro / BMAD output<br>
  <a href="https://github.com/cdeust/zetetic-team-subagents">zetetic-team-subagents</a> — 97 sourced reasoning patterns as specialist agents, each with its own scoped Cortex memory<br>
  <a href="https://github.com/cdeust/cortex-viz">hypermnesia-mcp-viz</a> — read-only visualization MCP (galaxy graph, execution trace, wiki browser) over this same store · <a href="https://github.com/cdeust/cortex-know-when-to-stop-training-model">cortex-beam-abstain</a> — retrieval abstention model for RAG
</p>

<p align="center">
  <sub><em><strong>Independent project:</strong> Cortex is an independent, open-source project. It is <strong>not an Anthropic product</strong> and is not affiliated with, sponsored by, or endorsed by Anthropic.</em></sub>
</p>

---

Your coding agent forgets you every time you close the session. Every architecture decision you explained. Every debugging session where you traced a bug through four layers of abstraction. Every "remember, we decided to use event sourcing, not CRUD" correction. Gone. Next session, your agent is a stranger to its own tools.

Cortex is a cross-platform persistent memory engine for AI coding agents, built on computational neuroscience. Codex, Gemini CLI, Claude Code, and any local stdio MCP host can use the same remember/recall, knowledge-graph, consolidation, and wiki tools. Claude Code's plugin adds automatic capture and injection hooks; other hosts use the same memory through explicit tool calls.

It runs **entirely on your machine** — a local SQLite database by default (zero setup, no services to install), or PostgreSQL + pgvector when you want it. A 22 MB embedding model, no LLM in the retrieval loop, no data leaving localhost.

> **36 neuroscience mechanisms · 52 memory tools · 9 lifecycle hooks · a self-curating, continuously-groomed per-project wiki — all local, all open-source.**

---

## Getting Started

Cortex ships as a single-click MCP bundle (`.mcpb`). Download the latest **`hypermnesia-mcp.mcpb`** from [Releases](https://github.com/cdeust/Cortex/releases), then open it in Claude Desktop — **Settings → Extensions** installs it in one click.

It runs immediately on the built-in **SQLite backend**: zero configuration, no database to provision, nothing to set up. Memory persists to a local file under `~/.claude/methodology/`. That's the whole install.

**Claude Cowork** works the same zero-setup way: the sandboxed environment is detected automatically (`CLAUDE_ENVIRONMENT=cowork`) and Cortex uses the local SQLite store — no PostgreSQL required.

Want PostgreSQL + pgvector instead (for very large stores or a shared team database)? It's a single configuration field — see [Configuration](#configuration) below. SQLite is the default; PostgreSQL is opt-in.

**Claude Code plugin (marketplace):**
```bash
claude plugin marketplace add cdeust/Cortex
claude plugin install hypermnesia-mcp
```
> **Upgrading from the `cortex` plugin?** The plugin was renamed `hypermnesia-mcp` in v4.15.0 (a community-directory name collision with an unrelated `cortex` plugin): `claude plugin uninstall cortex && claude plugin install hypermnesia-mcp` — your memories and configuration are untouched, storage paths do not change.
>
> **Upgrading from `cortex-viz@cortex-plugins`?** Its Claude Code marketplace identity was renamed in v3.0.0. Run `claude plugin uninstall cortex-viz@cortex-plugins`, then `claude plugin marketplace update cortex-plugins`, then `claude plugin install hypermnesia-mcp-viz@cortex-plugins`. The retained `cortex-viz@cortex-plugins` item is a frozen, nonfunctional migration shim: it only prints this notice and exposes no MCP server or tools. The repository remains `cdeust/cortex-viz`; only its marketplace plugin identity changed.
>
> Claude tool allowlists, hooks, skills, and agents must migrate both composed names: `mcp__plugin_cortex-viz_cortex-viz__open_visualization` becomes `mcp__plugin_hypermnesia-mcp-viz_hypermnesia-mcp-viz__open_visualization`, and `mcp__plugin_cortex-viz_cortex-viz__get_methodology_graph` becomes `mcp__plugin_hypermnesia-mcp-viz_hypermnesia-mcp-viz__get_methodology_graph`.

That is the whole install — zero configuration, no PostgreSQL, no system packages. The postInstall provisions Python dependencies and selects the local **SQLite** store (`~/.claude/methodology/memory.db`); the store schema auto-creates on first use. The embedding model is *not* downloaded at install time — it fetches lazily on first use (~100 MB, one-time; see [PRIVACY.md](PRIVACY.md)) and runs fully offline afterwards. The plugin path registers all lifecycle hooks (session-start context injection, per-prompt auto-recall, auto-capture, compaction checkpointing, the autonomous wiki cycle) and the `/cortex-setup-project` command.

An **existing PostgreSQL install is never downgraded**: the installer detects a configured `DATABASE_URL`, a prior PostgreSQL backend marker, or a reachable local `cortex` database and keeps using it across plugin updates.

**Upgrading the plugin to PostgreSQL (optional):**
```bash
bash <plugin-dir>/scripts/install-plugin.sh --postgres   # <plugin-dir> = the installed plugin root
```
In one line: PostgreSQL adds connection-pooled concurrency (two `psycopg_pool` latency classes), server-side PL/pgSQL WRRF fusion, and pgvector HNSW ANN indexing — worth it for very large stores or a shared team database (see [Under the Hood](#under-the-hood)); the memory tools and retrieval contract are identical on both backends. After upgrading, run `/cortex-setup-project` once — it handles pgvector setup, database creation, the embedding-model pre-cache, profile building, codebase seeding, and hook registration.

**What SQLite mode does *not* do (honest disclosure):** the WRRF fusion runs in-process instead of server-side, without HNSW ANN indexing (fine at personal-store scale, slower at very large scale); and three PostgreSQL-only hook enrichments degrade to silent no-ops — cross-agent team-decision injection (`agent_briefing`, plus the banner's Team Decisions section), file-based preemptive context (`preemptive_context`), and pipeline symbol heat-bumps (`pipeline_impact_bump`). Session-start banners, auto-recall injection, auto-capture, checkpoints, and all 52 memory tools work on both backends.

Verify any install:
```bash
python3 -m mcp_server.doctor
```
The check list is backend-aware: on SQLite it verifies Python, the store opens, a writable methodology dir, and the pool-capacity invariant; on PostgreSQL it additionally checks the PG driver, `DATABASE_URL`, connection, and extensions. Exit 0 means ready.

<details>
<summary><strong>More options</strong> (Clone, Docker, PyPI)</summary>

**Clone + setup script:**
```bash
git clone https://github.com/cdeust/Cortex.git && cd Cortex
bash scripts/setup.sh        # macOS / Linux
python3 scripts/setup.py     # Windows / cross-platform
```

**Docker:**
```bash
git clone https://github.com/cdeust/Cortex.git && cd Cortex
docker build -t cortex-runtime -f docker/Dockerfile .
docker run -it \
  -v $(pwd):/workspace \
  -v cortex-pgdata:/var/lib/postgresql/17/data \
  -v ~/.claude:/home/cortex/.claude-host:ro \
  cortex-runtime
```

**PyPI (`uvx` / `pip`) — best-effort hook-free compatibility:**
```bash
uvx hypermnesia-mcp          # run the MCP server directly
pip install hypermnesia-mcp  # or install into your environment
```
The server is published on PyPI as **`hypermnesia-mcp`** (registry name `io.github.cdeust/hypermnesia-mcp`). Claude Code remains the primary integration because it adds the lifecycle hooks; PyPI is the best-effort hook-free stdio compatibility channel for Gemini CLI, Codex CLI, and other MCP hosts.

**WSL / TLS client-cert / remote PostgreSQL:** See [deployment scenarios](docs/deployment-scenarios.md).

</details>

---

## Use with other MCP hosts

The MCP server is host-agnostic: any host that can launch a stdio process gets the full tool surface — `remember`, `recall`, the wiki, navigation, consolidation, all 52 tools — on the default local SQLite store. What is **not** portable are the 9 lifecycle hooks, which are Claude Code plugin machinery. The server itself does not import or require those hooks at startup.

**What works where (honest matrix):**

| Capability | Claude Code plugin | Local stdio hosts (Gemini CLI, Codex CLI, ChatGPT desktop, Cursor, Windsurf, VS Code, Agents SDK) | ChatGPT web |
|---|---|---|---|
| All 52 memory tools (`remember`, `recall`, wiki, navigation, consolidation, triggers, rules) | ✅ | ✅ | ❌ — Cortex does not ship a remote HTTPS endpoint |
| SQLite default store / PostgreSQL opt-in | ✅ | ✅ | ❌ — a remote deployment and per-user storage/auth model would be required |
| Auto-capture of significant tool output | ✅ (PostToolUse hook) | ❌ — store explicitly with `remember` | ❌ |
| Session-start context injection | ✅ (SessionStart hook) | ❌ — call `recall` yourself | ❌ |
| Per-prompt auto-recall | ✅ | ❌ | ❌ |
| Compaction checkpoints | ✅ | ❌ | ❌ |
| Autonomous wiki cycle (headless worker) | ✅ | ❌ — run `consolidate` / `curate_wiki` manually | ❌ |
| Cognitive profiling (`query_methodology`) | ✅ | ⚠️ profiles are mined from Claude Code session logs under `~/.claude/`; without them the profile is empty | ❌ |

In one sentence: on Claude Code memory is **ambient** (hooks capture and inject automatically); on every other host memory is **manual-tool-driven** — the agent stores and retrieves when instructed, and nothing happens between prompts.

The launch command on every host is the PyPI package (the `[sqlite]` extra enables sqlite-vec vector search; without it the store still works, with vector search disabled):

```bash
uvx --from "hypermnesia-mcp[sqlite]" hypermnesia-mcp
```

**Gemini CLI** — this repo ships a `gemini-extension.json`:

```bash
gemini extensions install https://github.com/cdeust/Cortex
```

Or add it to `~/.gemini/settings.json` directly:

```json
{
  "mcpServers": {
    "cortex": {
      "command": "uvx",
      "args": ["--from", "hypermnesia-mcp[sqlite]", "hypermnesia-mcp"]
    }
  }
}
```

**OpenAI Codex and ChatGPT desktop — native local plugin (recommended).** The
repository now carries an isolated Codex marketplace and an exact 10-tool
lean MCP surface. Claude Code remains the primary integration and retains its
automatic hooks, custom agent, and full tool profile. Its shared marketplace
catalog changes only for the pinned `hypermnesia-mcp-viz` 3.0.0 publication
and the frozen `cortex-viz` migration shim.
Pre-install the same published package once so the plugin's first `uvx`
handshake can reuse the local uv cache instead of spending its startup budget
downloading the Python environment. The bundled server also declares a
180-second startup ceiling, backed by a 110.46-second clean-cache launch
measured on 2026-08-02 on local macOS 26.5.1 arm64 with uv 0.8.19 (the clean
`ubuntu-latest` CI run completed in 23.87 seconds):

```bash
uv tool install "hypermnesia-mcp[sqlite]"
codex plugin marketplace add cdeust/Cortex
codex plugin add hypermnesia-mcp-codex@cortex-codex-plugins
```

Restart the ChatGPT desktop app and start a new task after installation. See
[the Codex plugin guide](docs/codex-plugin.md) for the host boundary and the
public-directory requirements Cortex deliberately does not claim.

**Direct Codex MCP configuration (fallback).** After the same pre-installation,
register the executable directly:

```bash
uv tool install "hypermnesia-mcp[sqlite]"
codex mcp add cortex --env CORTEX_MEMORY_STORE_BACKEND=sqlite -- hypermnesia-mcp
```

`codex mcp add` registers the executable and SQLite backend. For production use, extend that generated entry with explicit startup and tool timeouts. Codex CLI, the Codex IDE extension, and the ChatGPT desktop app's local Codex host share `~/.codex/config.toml`; the recommended complete entry is:

```toml
[mcp_servers.cortex]
command = "hypermnesia-mcp"
startup_timeout_sec = 30
tool_timeout_sec = 600

[mcp_servers.cortex.env]
CORTEX_MEMORY_STORE_BACKEND = "sqlite"
```

Verify discovery with `codex mcp list` and then `/mcp` inside a Codex session. ChatGPT **web** is a different surface: it does not read local Codex configuration and accepts MCP tools through hosted plugins backed by remote Streamable HTTP servers. Cortex deliberately does not claim that deployment model today; exposing a local personal-memory database through a remote endpoint would require an explicit authentication, tenancy, and privacy design.

The server preserves FastMCP's diagnostic startup banner (including the
`FASTMCP_SHOW_SERVER_BANNER` setting) but disables its network update probe: an
MCP stdio handshake must succeed offline and must not fail because of
proxy-specific HTTP extras. This does **not** freeze FastMCP indefinitely.
Upgrade the installed tool explicitly; the new Cortex release and its declared
dependency set are then resolved together:

```bash
uv tool upgrade hypermnesia-mcp
```

Repository installs remain reproducible through `uv.lock`, whose dependency
updates are reviewed through normal pull requests.

**Validation scope:** CI runs the installed production console entry point
through the MCP lifecycle under representative Claude, Gemini, and Codex client
identities for both the full and exact 10-tool lean profiles, then separately
invokes pinned vendor CLIs to parse the Claude plugin, Gemini extension, and
recommended Codex configuration. This proves the protocol and configuration
contracts; it does not simulate an authenticated model turn inside each vendor
UI.

**Cursor** — `.cursor/mcp.json` (project) or `~/.cursor/mcp.json` (global) — and **Windsurf** — `~/.codeium/windsurf/mcp_config.json` — take the same `mcpServers` block as Gemini above.

**VS Code** — `.vscode/mcp.json`:

```json
{
  "servers": {
    "cortex": {
      "type": "stdio",
      "command": "uvx",
      "args": ["--from", "hypermnesia-mcp[sqlite]", "hypermnesia-mcp"]
    }
  }
}
```

**OpenAI Agents SDK (Python):**

```python
from agents.mcp import MCPServerStdio

async with MCPServerStdio(
    name="cortex",
    params={
        "command": "uvx",
        "args": ["--from", "hypermnesia-mcp[sqlite]", "hypermnesia-mcp"],
    },
) as server:
    agent = Agent(name="Assistant", mcp_servers=[server])
```

`uvx` requires [uv](https://docs.astral.sh/uv/); `pip install "hypermnesia-mcp[sqlite]"` + the `hypermnesia-mcp` console script works identically. GUI hosts that don't inherit your shell `PATH` may need the absolute path from `which uvx`.

---

## Configuration

Cortex needs **no configuration** to run — the SQLite backend is the default and requires nothing. Two optional settings let you change the storage backend; in the single-click bundle they appear as fields in Claude Desktop's extension settings, and everywhere else they map to environment variables.

| Setting | Env var | Default | What it does |
|---|---|---|---|
| **Storage backend** | `CORTEX_MEMORY_STORE_BACKEND` | `sqlite`\* | `sqlite` runs fully local with zero setup. `postgresql` uses an external PostgreSQL + pgvector database (set the URL below). `auto` tries PostgreSQL and falls back to SQLite. |
| **PostgreSQL URL** | `CORTEX_MEMORY_DATABASE_URL` | *(empty)* | Only used when the backend is `postgresql` or `auto`. Example: `postgresql://user:password@host:5432/cortex`. Leave empty to stay on SQLite. Treated as sensitive. |

\* The single-click bundle pins the backend to `sqlite` through the manifest. If you run the server directly (clone / Docker) without setting the variable, the underlying code default is `auto` — it tries PostgreSQL and falls back to SQLite.

That's the entire surface most users touch. Both backends expose the **same 52 memory tools** (55 with the optional ai-architect-mcp-codebase + ai-architect-mcp-spec integrations) and the same retrieval contract; PostgreSQL adds server-side PL/pgSQL fusion and HNSW indexing that pays off at very large scale. Every other knob uses the `CORTEX_MEMORY_` prefix — see `mcp_server/infrastructure/memory_config.py`.

---

## Examples

A live, end-to-end run on the **SQLite backend** — store three memories, recall them by meaning, then check the store. The output is taken from the in-process FastMCP client (recall lists trimmed to the top hit). The harness writes with `force: true` for determinism, and the demo store already held a few earlier memories — so `memory_stats` totals exceed the three inserted here.

**1 — Store a memory.** It is stored with a heat score (`force: true` skips the dedup write-gate to keep the demo deterministic; omit it and a near-duplicate would be gated).

```js
remember({
  content: "Cortex stores memory in a local SQLite database by default — zero setup, no PostgreSQL required.",
  tags: ["architecture", "decision"],
  force: true
})
// → { stored: true, memory_id: 490, action: "stored", heat: 0.796 }
```

**2 — Recall by meaning, not keywords.** The fused retrieval ranks the relevant memory first.

```js
recall({ query: "how does cortex store memory by default?" })
// → memories[0] = {
//     content: "Cortex stores memory in a local SQLite database by default — zero setup, no PostgreSQL required.",
//     score: 0.0167, heat: 0.846, tags: ["architecture", "decision"]
//   }
```

**3 — A different query surfaces a different memory.** Stored "Anchored memories survive context compaction with maximum priority."; this recall puts it on top.

```js
recall({ query: "what survives context compaction?" })
// → memories[0] = {
//     content: "Anchored memories survive context compaction with maximum priority.",
//     heat: 0.565, tags: ["compaction"]
//   }
```

**4 — Inspect the store.** `has_vector_search: true` confirms semantic search is live on SQLite.

```js
memory_stats({})
// → { total_memories: 14, episodic_count: 8, semantic_count: 6,
//     avg_heat: 0.942, has_vector_search: true }
```

You rarely call these by hand: the lifecycle hooks (plugin install) inject the right memories at session start and capture new ones as you work. The tools are there when you want explicit control — `anchor` to pin an architecture constraint, `consolidate` to run a maintenance cycle, `narrative` to get the project's story so far.

---

## What's new

**v4.13.0 — grooming becomes continuous instead of session-bound.** A measured 76-day wiki-citation and lesson-promotion silence (invisible until this release could measure it) is closed by wiring a recurring citation-reconciliation pass and a lesson-promotion backlog count into every consolidation cycle, a new READ_ONLY `get_grooming_health` tool (backlog + staleness per grooming type, on demand), a one-line `session_start` nudge past a sourced staleness threshold, and an opt-in scheduled `scripts/groomer.py` entry point (dry-run by default) for anyone who wants the maintenance pass on its own cron/launchd cadence. Also fixed: headless wiki writes now go through the same governed path as interactive writes, and — found on the way — a CRITICAL latent bug where the anchor-page frontmatter template's `status: living` violated the `wiki.pages` CHECK constraint since its origin, silently failing the database sync of every interactively-authored `curate_wiki` page in production. **49 memory tools** (52 with upstream integrations). See [CHANGELOG.md](CHANGELOG.md) for the full write-up.

**v4.0.0 — the neuroscience model complete (13 new mechanisms).** Cortex fills the remaining cognitive-science gaps so memory spans encoding → consolidation → retrieval → forgetting with a grounded mechanism at every stage: source/reality monitoring (C1) with a confabulation gate, recollection-vs-familiarity dual-process retrieval (C2), claim-conflict monitoring (A2), goal maintenance (A1), attentional-salience gating, habituation (E1), fear-extinction inhibitory learning (E2), stress/arousal encoding-gain modulation, a predictive-coding forward model, value/reward-weighted retention, procedural (skill) memory (B1), two-phase NREM/REM sleep consolidation (F1), and cued targeted reactivation (F2). One new MCP tool (`recall_skills`); each mechanism is cited to published work and exposed as a live system vital. **44 memory tools** (47 with upstream integrations).

**v3.23.0 — single-click bundle + registry-indexer build fix.** Cortex now ships as an MCP bundle (`.mcpb`) with a `uv` runtime and a selectable storage backend — **SQLite by default, PostgreSQL optional** — so it installs in one click with zero setup. Also: a `neuro-cortex-memory` console script so `uv run neuro-cortex-memory` resolves from a checkout; registry indexers that build with `uv sync` and launch via that script now start the server and register all standalone tools **without** a PostgreSQL connection (so `tools/list` answers inside a DB-less container).

**v3.21.0 — visualization extracted to cortex-viz.** The entire visualization stack — the galaxy graph, execution trace, the Knowledge / Board / Wiki / Pipeline views, and their HTTP server — moves to a standalone companion MCP, **[cortex-viz](https://github.com/cdeust/cortex-viz)**, which reads this same store read-only. Cortex is a focused memory engine again (−50k lines). **Breaking:** the `open_visualization`, `get_methodology_graph`, and `query_workflow_graph` MCP tools are removed from Cortex — install the canonical `hypermnesia-mcp-viz` Claude Code plugin to get them back (its `/cortex-visualize` skill replaces the old one). 46 MCP tools remain; no memory, retrieval, or wiki behaviour changed; full suite green (3214 tests).

→ **[Full changelog and release notes](https://github.com/cdeust/Cortex/releases)**

---

## The science under the hood

Cortex doesn't store memories the way a database stores rows. It treats them the way a brain treats experiences. Every mechanism traces to a published paper — a **97-reference bibliography** ([docs/papers/bibliography.md](docs/papers/bibliography.md)).

**Memories have temperature.** Every memory starts hot. Access it and it stays hot; ignore it and it cools. Below a threshold it compresses: full text → summary → keywords → fades entirely. This is [rate-distortion optimal forgetting](docs/papers/thermodynamic-memory-vs-flat-importance.md) — the framework your brain uses to decide what's worth keeping. Important memories resist compression; surprising ones get a heat boost; boring, redundant ones quietly disappear. *(Anderson & Lebiere 1998; Ebbinghaus 1885)*

**Storage has a gatekeeper.** Not everything deserves to be remembered. Cortex maintains a predictive model of what it already knows and only stores information that violates its expectations. Tell it the same thing twice and the write gate blocks the second attempt. This is predictive coding — the mechanism your neocortex uses to filter sensory input. Only prediction errors get through. *(Friston 2005; Bastos et al. 2012)*

**Retrieval changes the memory.** When you recall a memory in a new context, Cortex compares the retrieval context against the storage context, and if there's enough mismatch it reconsolidates — updates the memory to reflect what's true now. Nader et al. showed in 2000 that retrieved memories become labile and can be rewritten. Your codebase evolves, and so do Cortex's memories of it. *(Dudai 2012; Nader et al. 2000)*

**Emotional memories are stronger.** Frustration during debugging, urgency in a production incident — Cortex detects emotional valence and encodes those memories with more force. They decay slower, compress later, and surface faster, like how you remember your worst outage in vivid detail but not last Tuesday's standup. *(Qasim et al. 2023; Hebb 1955)*

**Background consolidation runs like sleep.** When you're away, a consolidation cycle decays old memories, compresses verbose ones, promotes recurring patterns into general knowledge (episodic → semantic transfer), discovers entity relationships, and runs "dream replay" where related memories are compared and new connections emerge. *(McClelland et al. 1995; Foster & Wilson 2006; Buzsáki 2015)*

**Similar memories stay distinct.** Pattern separation, modeled on the dentate gyrus, keeps "Tuesday's standup" separate from "Wednesday's standup" even though they're nearly identical — without it, retrieval returns the same generic match for every similar query. *(Leutgeb et al. 2007; Yassa & Stark 2011)*

**Forgetting is active, not just passive decay.** Beyond the slow cooling of the heat model, Cortex runs two independent dopaminergic forgetting circuits from *Drosophila*: a permanent one that erodes a memory's trace under chronic interference (Rac1), and a transient one that blocks retrieval of a memory without erasing it (DAMB). Interference-heavy, low-value memories are actively removed rather than left to linger — the same way your brain prunes what competes without paying off. *(Davis & Zhong 2017; Sabandal et al. 2021)*

The two arXiv-ready papers go deeper: **[Thermodynamic Memory vs. Flat-Importance Stores (PDF, 34 pages)](docs/arxiv-thermodynamic/main.pdf)** · **[Stage-Aware Context Assembly (PDF, 39 pages)](docs/arxiv-context-assembly/main.pdf)**.

---

## What this actually feels like

**Monday.** You spend an hour debugging a webhook handler. After tracing through four layers, you find the root cause: a race condition in the Redis session store where TTL expiry can fire between the auth check and the permission lookup. You discuss the fix with Claude, decide on an approach, implement it. Session ends.

**Thursday.** Different project, but a user reports intermittent logouts. You open Claude. Before you even describe the bug, Cortex has already injected three memories: Monday's race-condition analysis, a decision from two weeks ago to use Redis for all session state, and a lesson from an older session about TTL edge cases in distributed caches.

Claude doesn't just have your conversation history. It has *context* — it connects the current problem to past decisions and skips the part where you re-explain your architecture.

**Three weeks later.** Those debugging sessions have consolidated into a general pattern: "authentication edge cases involving TTL-based caches." The specific Redis commands compressed to a summary, the debugging steps faded, the principle survived. Your next auth issue starts with institutional knowledge, not a blank page.

---

## Retrieval that actually works

We tested Cortex against three published benchmarks. All scores are **retrieval-only** — no LLM reader in the evaluation loop. We measure whether the right memory shows up, not whether a model can generate a good answer from it.

### LongMemEval — can you find a fact from 40 sessions ago?

LongMemEval (Wu et al., ICLR 2025): 500 human-curated questions embedded in ~40 sessions of conversation history (~115k tokens). The paper's best retrieval hit 78.4% Recall@10.

| | Cortex | What it means |
|---|---|---|
| Recall@10 | **98.2%** | The right memory shows up in the top 10 for nearly every question |
| MRR | **0.9167** | The correct *memory* is usually ranked first or second — retrieval rank only, no LLM reader |

<sub>n=500, clean-DB run `benchmarks/results/repro/20260714-v4.14.1-pretag/longmemeval-s.json`, code SHA `28145f0b7a113fc06e22568de6feea7f8444eaf5`, dirty=false.</sub>

| Category | MRR | R@10 |
|---|---|---|
| Single-session (assistant) | 1.000 | 100.0% |
| Multi-session reasoning | 0.964 | 100.0% |
| Knowledge updates | 0.932 | 100.0% |
| Single-session (user) | 0.841 | 95.7% |

Knowledge updates score near-perfect because the retrieval stack's recency signal and update-intent routing push the newest version of a fact above older ones.

Two categories — Temporal reasoning and Single-session (preference) — are withheld from this table. A confirmed same-protocol degradation exists between two committed, clean-tree runs (code SHA `0e858e8`, 2026-05-02, and this table's own `28145f0b`, 2026-07-14; identical `n=500`, `with_consolidation=false`, `--variant s` harness), and the responsible commit has not yet been isolated within the 269-commit window between them. Publishing the lower figure as the reference before the cause is found and fixed would misrepresent an open regression as a settled result. See `docs/benchmarks/arxiv-figure-audit-2026-08-02.md` § Per-category provenance for the full evidence and `docs/benchmarks/e1-v3-per-category.md` for both endpoints.

### LoCoMo — trick questions and multi-hop reasoning

LoCoMo (Maharana et al., ACL 2024): 1,986 questions across 10 conversations — adversarial trick questions, multi-hop queries needing evidence from multiple turns, and temporal reasoning.

| | Cortex | What it means |
|---|---|---|
| Recall@10 | **94.2%** | Right memory in top 10 over 9 times out of 10 |
| MRR | **0.8278** | The correct *memory* is typically ranked first — retrieval rank only, no LLM reader |

<sub>n=1986, BASELINE_NO_CONSOLIDATION, code SHA `ef178da7418a05bcf7aeb3e66f5b3179fdad2c4d` (before the plasticity fix `5f737fe`) — `docs/benchmarks/e1-v3-locomo-results.md`, backed by the committed artifact at `benchmarks/results/ablation/locomo_v3/`.</sub>

| Category | MRR | R@10 |
|---|---|---|
| Adversarial | 0.879 | 95.7% |
| Open-domain | 0.874 | 96.9% |
| Multi-hop | 0.781 | 89.4% |
| Single-hop | 0.743 | 94.3% |
| Temporal | 0.583 | 78.3% |

No LLM at query time. Five signals fused — vector similarity, full-text search, trigram matching, thermodynamic heat, recency — then reranked by a cross-encoder. On PostgreSQL the fusion runs server-side in PL/pgSQL; on SQLite the same five signals are fused in-process.

### BEAM — 10 million tokens of conversation

BEAM (Tavakoli et al., ICLR 2026) is the hardest long-term memory benchmark published: 10 conversations, each spanning 10 million tokens, probed across 10 memory abilities — including three no prior benchmark tests: contradiction resolution, event ordering, and instruction following. (Question counts vary by split: 196 on 10M, 395 on the current 100K.)

Every system in the paper collapses at this scale; the best reported (LIGHT on Llama-4-Maverick) scores 0.266 end-to-end. **The collapse is measurable — and structured assembly resists it.** Same code, same day, clean database, 35 conversations per split:

| Split | Flat WRRF | With Context Assembler | Δ |
|---|---|---|---|
| 500K (699 Qs) | 0.500 | **0.570** | +0.070 |
| 1M (695 Qs) | 0.466 | **0.535** | +0.069 |

<sub>Measured 2026-06-11 — `benchmarks/results/beam_crossover/RESULTS.md`. Flat retrieval degrades as the corpus doubles (0.500 → 0.466); the assembler holds a durable +0.07. At small scale it is net-flat (April 100K: 0.591 flat vs 0.602 assembled, 200-Q split since re-based to 395) — the value is scale-dependent, not universal.</sub>

**At 10M tokens the gap widens — and the assembler needs no labels:**

| Configuration | MRR | vs. flat WRRF (0.353) |
|---|---|---|
| Flat WRRF baseline | 0.353 | — |
| Assembler, oracle stage labels (BEAM `plan_id`) | 0.429 | +21.5% |
| Assembler, **temporal stage detection (timestamps only)** | **0.471** | **+33.4%** |

<sub>2026-04 family, same code revision, 196 Qs / 10 conversations — `benchmarks/beam/variance/assembler_10m_stagefixed.txt` and `assembler_10m_temporal.txt`. Reproduced 2026-06-11 on current code (fresh DBs, same 196 Qs): oracle 0.496, temporal **0.523** — the temporal advantage persists across code revisions (`benchmarks/results/beam10m_paired/RESULTS.md`).</sub>

The finding that surprised us: **label-free temporal day-level partitioning outperforms BEAM's ground-truth topic labels** (0.471 vs 0.429). Temporal proximity is a stronger stage signal than topic boundaries for conversational memory, so the [Stage-Aware Context Assembly](docs/papers/research-post-context-assembly.md) architecture deploys without any oracle metadata. It was originally designed in September 2025 for 9-page PRDs on Apple Intelligence's 4,096-token window ([ai-prd-builder](https://github.com/cdeust/ai-prd-builder), commit [`462de01`](https://github.com/cdeust/ai-prd-builder/commit/462de01)) — one month before the BEAM paper existed — because the problem is the same at both scales: you can't fit everything in context, so you have to be smart about what goes in.

> **Honest caveat:** BEAM defines no retrieval MRR metric — the paper uses LLM-as-judge nugget scoring. Our "MRR" is a retrieval proxy (rank of the first substring-matching memory); LIGHT's scores are end-to-end QA. The two are *not* commensurable, so we make no head-to-head BEAM claim and use BEAM only for within-system, same-harness comparisons.

<details>
<summary>Running benchmarks yourself</summary>

```bash
pip install -e ".[postgresql,benchmarks,dev]"

python benchmarks/beam/run_benchmark.py --split 100K          # ~10 min
CORTEX_USE_ASSEMBLER=1 python benchmarks/beam/run_benchmark.py --split 10M
python benchmarks/locomo/run_benchmark.py                     # ~40 min
python benchmarks/longmemeval/run_benchmark.py --variant s    # ~45 min
```

All scores on a fresh database (DROP + CREATE per run), TRUNCATE between conversations, FlashRank preflight verified. Full methodology: [docs/papers/research-post-context-assembly.md](docs/papers/research-post-context-assembly.md).

</details>

---

## Context that survives compaction

Claude has a 200k/1M token context window. During long sessions, when it fills, it compacts: summarizes older messages, strips tool outputs, paraphrases instructions. Important nuance evaporates; decisions you anchored early dissolve into vague summaries.

**Hippocampal Replay** fixes this — named after the phenomenon where your brain replays important experiences during sleep to consolidate them. It treats compaction as "sleep" and replays what matters when Claude "wakes up." Before compaction hits, a hook drains your active context — what you were working on, which files were open, what decisions you'd made, what errors were unresolved — and stores it as a checkpoint. After compaction, a second hook reconstructs context intelligently: the latest checkpoint, anything you'd anchored as critical, the hottest project memories, and predictions about what you'll need next.

You can be explicit about what matters:

```
cortex:anchor({ content: "We're using event-sourcing. All state changes go through the event bus.", reason: "Architecture constraint" })
```

Anchored memories get maximum protection — they always survive compaction, no matter what.

> The compaction checkpoint, session-start injection, and the autonomous wiki cycle are **lifecycle hooks** registered by the Claude Code plugin install. The single-click `.mcpb` bundle is a Directory connector — it delivers the 52 memory tools but **no hooks** (the MCPB format carries none). For the automatic session-lifecycle memory (session-start injection, auto-capture, compaction checkpointing, the autonomous wiki cycle), install the Claude Code plugin (see [More options](#getting-started)); the plugin also auto-registers the 3 upstream-integration tools when ai-architect-mcp-codebase / ai-architect-mcp-spec are present (55 total).

---

## The autonomous wiki

Cortex's wiki is **a self-curating per-project knowledge base**, not a memory dump. Every project the registry knows is driven toward **42 canonical documentation scopes** (product overview, architecture, services, API, data flow, operations, decisions, onboarding, security, testing, configuration … ), and every source file toward **13 canonical sections** (Purpose · Public API · Dependencies · Callers · How it works · Invariants · What can go wrong · Tests · Sequence diagram · Flow diagram · Parameters · Request example · Response example).

What makes it autonomous — no cron, no daemon, no manual invocation:

- **A `SessionStart` hook spawns a background `consolidate` cycle** every 6 hours (TTL stamp at `~/.claude/methodology/.last_consolidate`). The agent runs because you opened Claude Code, and stops when nothing is left to author.
- **A curation-gap detector + headless authoring worker.** Each file-doc page declares its missing sections in frontmatter (`curation_gaps:`); the worker drains them by invoking `claude -p` (your existing credentials, no API key), which calls the codebase-intelligence MCP tools — `codebase_context`, `codebase_impact`, `codebase_query` — to ground each section in the real call graph before writing.
- **Missing-anchor authoring.** When a project has no architecture / services / api / data-flow / operations / ADR / PRD page, the worker authors it from the source tree (structure + README + manifest + `CLAUDE.md`), same grounding.
- **Drift detection.** Pages whose cited source moved, whose mtime is stale (>60 days), or whose body is off-template are flagged and re-authored in place. Deletion is never the policy; **visibility** is — a yellow banner shows `⚠ Page N% curated — M sections still missing` and exactly what belongs in each.
- **ADRs as task-records.** Every completed task (≥1 commit at session end) auto-drafts an ADR with five mandatory sections (Entry / Mandatory / How / Result / Serves) from commit subjects + the session's memories; the worker refines it next cycle.
- **Per-project dashboards** at `wiki/_dashboards/<project>.md` show slot-fill rate, file coverage %, open gaps, and the queue for the next cycle.
- **Continuous mechanical grooming.** A recurring citation-reconciliation pass and a lesson-promotion backlog count run inside every consolidation cycle, not just when a session author happens to be active — closing a gap that let a 76-day, multi-thousand-item wiki-citation and lesson-promotion backlog go entirely unnoticed. `get_grooming_health` (a READ_ONLY MCP tool) reports exact backlog + last-run age per grooming type on demand; `session_start` prints one line when any type exceeds a sourced staleness threshold (3× the measured p90 gap between consolidation cycles). A `scripts/groomer.py` scheduled entry point (dry-run by default, opt-in `--apply`) is shipped for anyone who wants the maintenance pass to also run on its own cron/launchd schedule, independent of live sessions.

This isn't documentation you write — it's documentation Cortex authors, grooms, and verifies for you, every 6 hours, until every project reaches full scope coverage and every source file has all 13 sections filled.

### Write papers in Cortex

Every page is editable in place in a full scientific writing environment — the same markdown that feeds the memory pipeline, with a rendering layer on top that never steals your content into a proprietary format. Your `.md` files stay grep-able, diffable, and git-versioned.

- **CodeMirror 6 split-pane editor** — syntax-highlighted markdown on the left, fully-rendered article on the right, atomic round-trip to the `.md` file on disk.
- **Structured frontmatter** — `kind` / `domain` / `scope` / `status` / `authored_by` / `provenance` / `created` / `updated` / `last_reviewed`. Real metadata: the coverage audit, dashboards, and wiki view all read it.
- **`[[wiki/path]]` cross-references** rendered as clickable links (bare slugs route to filtered search), with a backlinks footer.
- **Mermaid diagrams with a 🔍 lens** — viewport-sized viewer with wheel-zoom, drag-pan, and keyboard shortcuts.
- **LaTeX math** via KaTeX, **BibTeX citations** (`[@friston2010]` → `(Friston 2010)` with an auto APA bibliography), and **figure / equation / table auto-numbering** with cross-refs.
- **Pandoc export** — one click to PDF (via LaTeX), TEX, DOCX, or HTML. Journal-submittable from the same source.

> The wiki's editor, galaxy graph, and views render through the standalone **[hypermnesia-mcp-viz](https://github.com/cdeust/cortex-viz)** MCP, which reads this same store read-only.

---

## Agent Integration

Cortex works with teams of specialized agents — and it **uses one itself**: the headless wiki worker is a Claude agent that drains the curation queue every six hours (see [the autonomous wiki](#the-autonomous-wiki)). Memory is shared across a team via Wegner's transactive-memory model (1987): teams store more than individuals because each member specializes.

- **Specialization** — each agent writes to its own `agent_topic`. Engineer's debugging notes don't clutter tester's recall; the wiki worker writes to `agent_topic=wiki-curation` so its drafts stay out of interactive recall.
- **Coordination** — decisions auto-protect and propagate. When engineer decides "use Redis over Memcached," every agent sees it at next session start. The ADRs the worker drafts at session end *are* the cross-agent shared memory.
- **Directory** — entity-based queries span all topics. "What do we know about the reranker?" returns results from engineer, tester, researcher, and the worker's drafts alike.

<p align="center">
<img src="docs/diagram-team-memory.svg" alt="Transactive Memory System" width="80%"/>
</p>

Works with any custom agents. See [zetetic-team-subagents](https://github.com/cdeust/zetetic-team-subagents) for a ready-made team of specialists, each with scoped memory.

---

## The rest of the stack

Cortex fixes what an agent **forgets**. Three sibling MCP servers fix what it **can't see**, what it **can't verify**, and how it **reasons**. Each installs on its own — none requires the others — and Cortex registers extra tools automatically when it finds them.

| | The problem it solves | Install it when | Related work |
|---|---|---|---|
| **[ai-architect-mcp-codebase](https://github.com/cdeust/ai-architect-mcp-codebase)** | Your agent answers structural questions ("who calls this?", "what breaks if I change it?") by re-reading files, burning context and missing cross-file callers. Indexes the repo into a property graph: call/import resolution, Leiden communities, hybrid BM25+TF-IDF search, impact analysis. | Refactoring, root-cause work, or any repo big enough that `grep` stops being an answer. | [codebase-memory-mcp](https://github.com/DeusData/codebase-memory-mcp) covers far more languages (158). ai-architect-mcp-codebase is narrower but **qualifies every impact answer as `exact` or `lower-bound`** instead of presenting a possibly-incomplete list as complete. |
| **[ai-architect-mcp-spec](https://github.com/cdeust/ai-architect-mcp-spec)** | Specs pass review, then the implementation quietly contradicts them. Turns a feature description into a 9-file PRD and *verifies* it — deterministic Hard Output Rules plus multi-judge consensus calibrated against external oracles (schema / math / code). | You already write specs and want a gate that fails, not a template that hopes. | [spec-kit](https://github.com/github/spec-kit), [BMAD](https://github.com/bmad-code-org/BMAD-METHOD) and Kiro **generate** specs. This **verifies** them — it runs as a CI gate over their output rather than replacing them. |
| **[zetetic-team-subagents](https://github.com/cdeust/zetetic-team-subagents)** | Subagents that assert confidently instead of citing. 11 problem-shaped skills over 97 sourced reasoning patterns (Curie to Toulmin), plus a pre-commit gate that blocks unsourced constants. | You want "I don't know" to be an available answer, and every constant in your code to trace to a paper or a benchmark. | Collections like [wshobson/agents](https://github.com/wshobson/agents) organise agents **by role**. These are organised **by problem shape**, and each carries its epistemic method and sources. |
| **[hypermnesia-mcp-viz](https://github.com/cdeust/cortex-viz)** | Memory you can't inspect is memory you can't trust. Read-only galaxy graph, execution trace, and wiki browser over this same store. | You want to see what Cortex actually kept, and why. | — |

---

## Architecture

Clean Architecture with strict dependency rules — inner layers never import outer layers.

<p align="center">
<img src="docs/diagram-architecture.svg" alt="Clean Architecture layers" width="80%"/>
</p>

| Layer | What lives here | Modules |
|---|---|---|
| **shared/** | Pure utilities (text, hash, similarity, types) | 18 |
| **core/** | Neuroscience + retrieval + wiki-curation logic | 177 |
| **core/context_assembly/** | Structured context assembler + stage detector | 10 |
| **infrastructure/** | SQLite + PostgreSQL stores, embeddings, file I/O, MCP client | 59 |
| **handlers/** | MCP tools + consolidation cycles (50 MCP-exposed; 53 with upstream integrations) | 105 |
| **hooks/** | Lifecycle automation (incl. autonomous consolidate spawn) | 9 registered |
| **server/** | MCP tool registration + composition roots | — |
| **observability/** | Prometheus text-format metrics | 2 |

**Storage:** SQLite by default (a single local file, zero setup) or PostgreSQL 15+ with pgvector (HNSW) and pg_trgm. Both back the same 52 tools and the same WRRF fusion of five signals — vector search, FTS, trigram, heat, recency. On PostgreSQL it runs server-side in PL/pgSQL stored procedures; on SQLite the equivalent fusion runs in-process (vector search included, as the live `memory_stats` `has_vector_search` flag confirms).

**Concurrency (PostgreSQL):** `psycopg_pool.ConnectionPool` with two latency classes — `interactive_pool` (min=2, max=8) for recall/remember/anchor, `batch_pool` (min=1, max=2) for consolidate/ingest. Tool handlers run on worker threads via `asyncio.to_thread`; per-tool admission semaphores bound fan-out. Heat is computed at read time by `effective_heat()`, so homeostatic maintenance writes one scalar per domain per run instead of N rows.

**Configuration:** select the backend with `CORTEX_MEMORY_STORE_BACKEND` (`sqlite` / `postgresql` / `auto`); set `CORTEX_MEMORY_DATABASE_URL` for the PostgreSQL path. All other parameters use the `CORTEX_MEMORY_` prefix — see `mcp_server/infrastructure/memory_config.py`. Wiki cycle TTL is `CORTEX_CONSOLIDATE_TTL_HOURS` (default 6h).

---

## Verification

Every benchmark headline above is backed by a per-mechanism ablation campaign — full *n*, single-seed, with code SHAs, dirty flags, manifests, and per-row JSON preserved:

- **LongMemEval-S, 17 rows, n=500** — `docs/benchmarks/e1-v3-results.md`. Per-mechanism deltas at the calibrated equilibrium + category-specialization analysis.
- **LoCoMo, 14 rows, n=1986** — `docs/benchmarks/e1-v3-locomo-results.md` (pre-fix) and `docs/benchmarks/e1-v3-locomo-results-post-fix.md` (post plasticity result-shape fix). Two-baseline design (NO_CONSOLIDATION / WITH_CONSOLIDATION).

The full per-mechanism evidence lives in the thermodynamic paper (§6.3); the BEAM decay dose-response (§6.4) documents a re-scoped negative result after a dirty-store confound was caught and traced. **[Thermodynamic Memory vs. Flat-Importance Stores (PDF, 34 pages)](docs/arxiv-thermodynamic/main.pdf)** · **[Stage-Aware Context Assembly (PDF, 39 pages)](docs/arxiv-context-assembly/main.pdf)**.

---

## Security

Runs **100% locally** — MCP over stdio, the storage backend (SQLite file or PostgreSQL on localhost) never leaves your machine (the optional [hypermnesia-mcp-viz](https://github.com/cdeust/cortex-viz) companion binds its server to 127.0.0.1). No data leaves your machine. SafeSkill scan: **94/100** (code 97, content 88 — [docs/safeskill-report.json](docs/safeskill-report.json)).

## Privacy Policy

Cortex is **local-first**: your memories, conversations, and profiles stay on your machine — stored in a local SQLite database (`~/.claude/methodology/memory.db`) by default, or in a PostgreSQL database you control. Cortex sends **no** memories, content, or telemetry to the author, Anthropic, or any third party. The only outbound network activity is a one-time download of open-source embedding/reranking models from Hugging Face (model files only), plus any integrations you explicitly configure. Full policy: **[PRIVACY.md](PRIVACY.md)**.

## Support

- **Issues & bug reports:** [GitHub Issues](https://github.com/cdeust/Cortex/issues)
- **Security disclosures:** see [SECURITY.md](SECURITY.md)
- **Contact:** [admin@ai-architect.tools](mailto:admin@ai-architect.tools)

## Development

```bash
pytest                    # full suite (see assets/badge-tests.svg for the current count)
ruff check .              # Lintruff format --check .     # Format
python scripts/check_doc_claims.py   # advertised counts must match the repo
```

Contributing: [CONTRIBUTING.md](CONTRIBUTING.md) · Who decides and what happens
if the maintainer stops: [GOVERNANCE.md](GOVERNANCE.md) · Where the project is
going: [docs/ROADMAP.md](docs/ROADMAP.md) · The security argument and its
limits: [docs/ASSURANCE-CASE.md](docs/ASSURANCE-CASE.md).

## License

MIT — see [LICENSE](LICENSE).

This software is the independent work of Clément Deust. It was developed
outside any employment relationship and is not affiliated with, endorsed by,
or owned by any past or present employer. It is part of the ai-architect
ecosystem ([zetetic-team-subagents](https://github.com/cdeust/zetetic-team-subagents),
[ai-architect-mcp-codebase](https://github.com/cdeust/ai-architect-mcp-codebase),
[ai-architect-mcp-spec](https://github.com/cdeust/ai-architect-mcp-spec)).

The neuroscience and information-retrieval algorithms encoded in this
software are derived from published academic work cited in
[`docs/papers/bibliography.md`](docs/papers/bibliography.md) and inline in the
source via `# source:` annotations (Friston on predictive
coding, Anderson & Lebiere on rate-distortion forgetting, Nader et al. on
retrieval-induced lability, McClelland et al. on consolidation, and others).
The MIT license covers this implementation; it does not assert ownership over
the underlying mechanisms, which remain attributable to their original
authors and publications.

## Citation

The paper PDFs on `main` are the canonical artefacts (arXiv IDs forthcoming, endorsement in progress):

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
