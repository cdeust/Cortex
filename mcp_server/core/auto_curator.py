"""Auto-curator — turn PG memory clusters into curated wiki pages.

This module is the systemic answer to "ALL ACTIONS SHOULD BE DOCUMENTED
BY OPUS 4.7" (user directive 2026-05-17). Manual authoring doesn't
scale; periodic mechanical extraction produces empty templates. The
auto-curator sits in between:

  1. Cluster recent PG memories into topic groups (entity co-occurrence +
     heat + domain).
  2. For each cluster that earns a wiki page (≥ N memories, ≥ heat
     threshold, no existing fresh page), construct a structured
     **authoring prompt** that encodes the wiki-page conventions
     (frontmatter, lead, sections with diagrams, "why this not the
     alternatives", "what can go wrong", "see also", primary sources).
  3. Return the prompts as "curation jobs". A downstream LLM (the
     conversational Opus 4.7 via the ``curate_wiki`` MCP tool, or a
     direct Anthropic API call when ``ANTHROPIC_API_KEY`` is set)
     authors the page and writes it via ``wiki_write``.

Pure business logic — no I/O. The handler composes this with the memory
store and the wiki writer.

References (the user-quoted directives this module exists to satisfy):
  * "ALL ACTIONS SHOULD DOCUMENTED BY OPUS 4.7, IT'S NOT POSSIBLE THE
    LLM IS NOT ABLE TO PRODUCE A DOCUMENTATION FROM AN ACCESS."
  * "If I open the wiki I should be able to parse the documentation and
    understand in a clear way how the whole codebase work, what it does,
    and how it was built."
  * "The documentation you created now, should be auto created and auto
    curated."
"""

from __future__ import annotations

from mcp_server.core.prose_redaction import REDACTION_CONVENTIONS

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

# 2026-05-17: thresholds tuned to mirror the cluster-quality bar of the
# hand-authored pages from this session. Below these, a cluster doesn't
# carry enough signal to author a useful page.
MIN_MEMORIES_PER_CLUSTER = 4
MIN_AVG_HEAT_FOR_PAGE = 0.3
MIN_ENTITY_FREQ_FOR_TOPIC = 3
MAX_MEMORIES_PER_PROMPT = 25  # cap prompt size; cross-encoder picks the best

# source: pre-existing tuned values, extracted unchanged (#197 family 3);
# provenance not recorded at introduction
_MIN_ENTITY_LEN = 4  # shorter identifiers are too generic to name a topic
_MIN_SNAKE_ENTITY_LEN = 6  # snake_case identifiers below this are noise
_MEMORY_HEAD_CHARS = 1200  # per-memory excerpt cap in authoring prompts
_EXISTING_BODY_CHARS = 4000  # existing-page excerpt cap in re-author prompts

# ── Data structures ─────────────────────────────────────────────────────


@dataclass
class CurationCluster:
    """A topic-cohesive group of memories that warrants a single page."""

    topic: str  # e.g. "predictive-coding-gate" — derived from dominant entity
    domain: str  # cortex / agentic-ai / etc.
    suggested_kind: str  # reference / lesson / adr
    suggested_path: str  # e.g. "reference/cortex/predictive-coding-gate.md"
    memory_ids: list[int] = field(default_factory=list)
    memory_contents: list[str] = field(default_factory=list)
    memory_tags: list[list[str]] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)  # top entities by frequency
    avg_heat: float = 0.0
    earliest_at: str = ""
    latest_at: str = ""


@dataclass
class CurationJob:
    """One authoring task: cluster + prompt ready for the LLM."""

    cluster: CurationCluster
    prompt: str
    related_pages: list[str] = field(default_factory=list)  # paths for [[wiki-links]]


# 2026-05-17: how recent counts as "already authored" — skip re-curating a
# cluster whose suggested path was written within this window. 30 days
# is the heuristic floor; clusters with substantial new content after
# that window get re-curated to update the page.
SKIP_IF_AUTHORED_WITHIN_DAYS = 30


def is_path_recently_authored(
    suggested_path: str,
    wiki_root: str,
    within_days: int = SKIP_IF_AUTHORED_WITHIN_DAYS,
) -> bool:
    """True if ``<wiki_root>/<suggested_path>`` exists and was modified
    within the last ``within_days``. Used to skip clusters whose page
    already exists and is fresh.

    The check is filesystem-mtime based — no PG lookup needed. If a
    user edits a page by hand, the mtime updates and the cluster stays
    skipped (their edits aren't clobbered).
    """
    import os
    import time

    full = os.path.join(wiki_root, suggested_path)
    if not os.path.isfile(full):
        return False
    age_seconds = time.time() - os.path.getmtime(full)
    return age_seconds < (within_days * 86400)


# ── Topic identification ────────────────────────────────────────────────


_TOPIC_STOPWORDS = frozenset(
    {
        "the",
        "a",
        "an",
        "and",
        "or",
        "but",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "can",
        "this",
        "that",
        "these",
        "those",
        "to",
        "of",
        "for",
        "in",
        "on",
        "at",
        "by",
        "with",
        "from",
        "as",
        "into",
        "user",
        "tool",
        "command",
        "file",
        "output",
        "error",
        "input",
        "result",
        "decision",
        "lesson",
    }
)


def _slugify(text: str, max_len: int = 60) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:max_len].rstrip("-")


_FILE_EXT_RE = re.compile(r"\b([\w./_-]+)\.(py|ts|js|md|sql|yml|yaml|toml|rs|go)\b")
_CAMEL_RE = re.compile(r"\b[A-Z][a-zA-Z]+(?:[A-Z][a-z]+)+\b")
_SNAKE_RE = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b")


def extract_entities_from_content(content: str) -> list[str]:
    """Crude entity extraction — proper nouns, file paths, function names.

    Canonicalisation:
      - File paths drop the extension (``foo/bar.py`` → ``bar``) so the
        same module mentioned with and without extension counts as the
        same entity.
      - File paths drop the directory prefix to keep cluster topics
        readable. The full path is still in the source memory.

    Mirrors mcp_server/core/knowledge_graph.py's heuristic NER but kept
    local to avoid coupling auto-curator to the knowledge-graph subsystem.

    Public (promoted from ``_extract_entities_from_content``, INC7.8/M-D8,
    2026-07-11): reused as-is by ``core/distillation.py`` for
    error->success dossier pairing — a second cross-module call site for
    the same lexical-entity heuristic, same rationale as this docstring's
    original one (avoid a heavier coupling to knowledge_graph.py).
    """
    entities: list[str] = []
    # File-path-like tokens — canonicalise to the basename without extension
    for m in _FILE_EXT_RE.finditer(content):
        full = m.group(1)  # the part before the dot
        basename = full.rsplit("/", 1)[-1]
        if len(basename) >= _MIN_ENTITY_LEN:
            entities.append(basename)
    # CamelCase identifiers
    for m in _CAMEL_RE.finditer(content):
        entities.append(m.group(0))
    # snake_case identifiers ≥ 6 chars
    for m in _SNAKE_RE.finditer(content):
        if len(m.group(0)) >= _MIN_SNAKE_ENTITY_LEN:
            entities.append(m.group(0))
    return entities


def _cluster_topic_from_entities(entities: list[str]) -> str:
    """Pick a topic label from a list of entities (most-frequent wins)."""
    if not entities:
        return "untitled"
    c = Counter(entities)
    top = c.most_common(1)[0][0]
    # Strip extension if present
    return top.rsplit(".", 1)[0]


# ── Clustering ──────────────────────────────────────────────────────────


def build_clusters(
    memories: list[dict],
    *,
    domain: str | None = None,
    min_memories: int = MIN_MEMORIES_PER_CLUSTER,
    min_avg_heat: float = MIN_AVG_HEAT_FOR_PAGE,
    wiki_root: str | None = None,
    skip_recently_authored: bool = True,
) -> list[CurationCluster]:
    """Group memories into topic clusters via dominant-entity bucketing.

    Strategy:
      1. Extract entities from each memory's content.
      2. Assign each memory to its top entity (the one with highest
         document frequency within the memory's content).
      3. Group memories by assigned entity.
      4. Filter: clusters below ``min_memories`` or below
         ``min_avg_heat`` are dropped — they don't earn a page yet.

    Returns clusters sorted by combined size × avg_heat descending so
    high-value clusters are curated first.

    No LLM call here — this is pure logic. The LLM gets called downstream
    by the handler with the prompts ``build_authoring_prompt`` produces.
    """
    if not memories:
        return []

    # Step 1+2: assign each memory to its dominant entity
    buckets: dict[str, list[dict]] = defaultdict(list)
    for mem in memories:
        if domain and mem.get("domain") != domain:
            continue
        content = mem.get("content") or ""
        entities = extract_entities_from_content(content)
        if not entities:
            continue
        # Dominant entity = most frequent
        top_entity = Counter(entities).most_common(1)[0][0]
        # Skip too-generic entities
        if top_entity.lower() in _TOPIC_STOPWORDS or len(top_entity) < _MIN_ENTITY_LEN:
            continue
        buckets[top_entity].append(mem)

    # Step 3+4: build clusters
    clusters: list[CurationCluster] = []
    for entity, mems in buckets.items():
        if len(mems) < min_memories:
            continue
        avg_heat = sum(m.get("effective_heat", m.get("heat", 0.0)) for m in mems) / len(
            mems
        )
        if avg_heat < min_avg_heat:
            continue
        # Aggregate all entities across cluster memories for richer context
        all_entities: list[str] = []
        for m in mems:
            all_entities.extend(extract_entities_from_content(m.get("content") or ""))
        top_entities = [e for e, _ in Counter(all_entities).most_common(8)]
        topic = entity
        slug = _slugify(topic)
        # Pick kind heuristically — could be improved by tag inspection
        kind = _infer_kind(mems)
        dom = (mems[0].get("domain") or "cortex").lower()
        path = f"{_kind_dir(kind)}/{dom}/{slug}.md"
        clusters.append(
            CurationCluster(
                topic=topic,
                domain=dom,
                suggested_kind=kind,
                suggested_path=path,
                memory_ids=[m["id"] for m in mems if "id" in m],
                memory_contents=[m.get("content") or "" for m in mems],
                memory_tags=[m.get("tags") or [] for m in mems],
                entities=top_entities,
                avg_heat=avg_heat,
                earliest_at=min((m.get("created_at") or "") for m in mems),
                latest_at=max((m.get("created_at") or "") for m in mems),
            )
        )

    # 2026-05-17: skip clusters whose suggested page already exists and
    # was authored within ``SKIP_IF_AUTHORED_WITHIN_DAYS``. Without this
    # filter the curator keeps re-suggesting the same topics on every
    # call, even after a page was just authored. Caller passes the wiki
    # root path (``WIKI_ROOT``); when omitted we don't filter (useful
    # for tests).
    if skip_recently_authored and wiki_root:
        clusters = [
            c
            for c in clusters
            if not is_path_recently_authored(c.suggested_path, wiki_root)
        ]

    # Rank by size × avg_heat
    clusters.sort(key=lambda c: len(c.memory_ids) * c.avg_heat, reverse=True)
    return clusters


def count_pending_clusters(
    memories: list[dict],
    *,
    domain: str | None = None,
    wiki_root: str | None = None,
) -> int:
    """Count how many clusters would yield a fresh authoring job.

    Thin wrapper over the streaming counter (one chunk) so the list and
    streaming paths can't diverge.
    """
    return count_pending_clusters_streamed(
        [memories], domain=domain, wiki_root=wiki_root
    )


def count_pending_clusters_streamed(
    memory_chunks,
    *,
    domain: str | None = None,
    min_memories: int = MIN_MEMORIES_PER_CLUSTER,
    min_avg_heat: float = MIN_AVG_HEAT_FOR_PAGE,
    wiki_root: str | None = None,
    skip_recently_authored: bool = True,
) -> int:
    """Count pending cluster jobs in ONE streaming pass — no resident corpus.

    ``build_clusters`` buckets each memory by its dominant entity (a per-memory
    key, not pairwise clustering), so the *count* needs only per-entity
    aggregates: a count, a heat sum, a tag counter (for the kind→path the
    recently-authored filter needs), and the first-seen domain. Peak RAM is
    O(num_entities), not O(N). Mirrors ``build_clusters``'s gates exactly; the
    full memory-bearing clusters are still built on demand by ``curate_wiki``.
    """
    buckets: dict[str, dict] = {}
    for chunk in memory_chunks:
        for mem in chunk:
            if domain and mem.get("domain") != domain:
                continue
            entities = extract_entities_from_content(mem.get("content") or "")
            if not entities:
                continue
            top_entity = Counter(entities).most_common(1)[0][0]
            if (
                top_entity.lower() in _TOPIC_STOPWORDS
                or len(top_entity) < _MIN_ENTITY_LEN
            ):
                continue
            b = buckets.get(top_entity)
            if b is None:
                b = {"count": 0, "heat_sum": 0.0, "tags": Counter(), "domain": None}
                buckets[top_entity] = b
            b["count"] += 1
            b["heat_sum"] += mem.get("effective_heat", mem.get("heat", 0.0))
            for t in mem.get("tags") or []:
                b["tags"][t.lower()] += 1
            if b["domain"] is None:
                b["domain"] = (mem.get("domain") or "cortex").lower()

    count = 0
    for entity, b in buckets.items():
        if b["count"] < min_memories:
            continue
        if b["heat_sum"] / b["count"] < min_avg_heat:
            continue
        if skip_recently_authored and wiki_root:
            kind = _infer_kind_from_tags(b["tags"])
            path = f"{_kind_dir(kind)}/{b['domain']}/{_slugify(entity)}.md"
            if is_path_recently_authored(path, wiki_root):
                continue
        count += 1
    return count


def _infer_kind(memories: list[dict]) -> str:
    """Decide whether the cluster is a reference, lesson, or adr."""
    tag_counter: Counter[str] = Counter()
    for m in memories:
        for t in m.get("tags") or []:
            tag_counter[t.lower()] += 1
    return _infer_kind_from_tags(tag_counter)


def _infer_kind_from_tags(tag_counter: Counter[str]) -> str:
    """Kind decision from an already-accumulated lower-cased tag counter.

    Shared by ``_infer_kind`` (list path) and the streaming cluster counter,
    which folds tags per bucket online instead of holding the memory list.
    """
    if tag_counter.get("decision", 0) > 0 or tag_counter.get("adr", 0) > 0:
        return "adr"
    if (
        tag_counter.get("lesson", 0) > 0
        or tag_counter.get("learned", 0) > 0
        or tag_counter.get("postmortem", 0) > 0
    ):
        return "lesson"
    return "reference"


def _kind_dir(kind: str) -> str:
    return {"adr": "adr", "lesson": "lessons", "reference": "reference"}.get(
        kind, "reference"
    )


# ── Authoring-prompt construction ──────────────────────────────────────


_ADR_TASK_RECORD_SECTIONS = """\
For kind = `adr` (task-record): the body MUST carry these sections in this exact \
order. They are mandatory — no skipping:

1. **## Status** — `proposed` / `accepted` / `rejected` / `superseded`. New \
task-records default to `accepted` (the work is done).
2. **## Entry** — the problem, task, or trigger as it stood before the work began. \
State the symptom or the request; do not speculate about root cause yet.
3. **## Mandatory elements** — constraints that had to be respected: Clean \
Architecture / SOLID rules, layer dependency rule, project invariants (no SQLite, \
source-citation discipline, file-size limits), compatibility windows, security gates, \
paper-grounded equations, contracts with upstream/downstream systems. Be specific. \
List, not prose.
4. **## How** — the approach taken: implementation steps, technical choices, the \
sequence of moves. Reference specific source files with full paths. Name alternatives \
that were tried and abandoned.
5. **## Result** — what was actually delivered. Cite the commit hash, the benchmark \
run, or the artifact that proves the outcome. If partial, state precisely what is and \
is not done.
6. **## Serves** — what this enables downstream. Which subsystem depends on it, which \
invariant it upholds, which user-visible behaviour it supports. The "why it stays in \
the codebase" answer.
7. **## Alternatives considered** — formally-considered-and-rejected designs (distinct \
from "things we tried"; those go in How).
8. **## References** — paper citations, ADR cross-refs as `[[adr/...]]`, related \
task-records.
"""

_GENERIC_STRUCTURE_SECTIONS = """\
For kind = `reference` / `explanation` / other: the body should follow this \
conventional shape:

1. **# <title>** — H1 matching frontmatter title.
2. **Lead paragraph** — one paragraph saying what the page is and why a reader should \
care.
3. **Sections explaining the topic**:
   - Use ```mermaid``` fences for flowcharts, sequence diagrams, state diagrams when \
the topic involves dataflow or state transitions.
   - Use tables for taxonomies, parameter lists, comparisons.
   - Use ``` fences with language for code snippets.
   - Cite specific source files with full paths (e.g. \
``mcp_server/core/predictive_coding_gate.py``).
4. **## Why this design and not the alternatives** — explain the architectural choice. \
What was considered, what was rejected, why.
5. **## What can go wrong** — failure modes the next reader should know about, with \
concrete symptoms.
6. **## See also** — cross-links to related pages using `[[wiki/path]]` notation, plus \
specific source files.
7. **## Primary sources** — if the topic touches research literature, cite the actual \
papers with full citations.
"""


WIKI_AUTHORING_PROMPT = """You are Opus 4.7 authoring a single wiki page for the \
Cortex persistent-memory MCP server.

You are given a topic-cohesive cluster of PG memories (tool events, decisions, \
lessons, notes) plus the suggested wiki path and any existing related wiki pages for \
cross-linking.

# Your task

Author **one** curated wiki page in Markdown that follows the Cortex documentation \
conventions below. The page must be substantive (target 8-15 KB), with structure, \
prose, diagrams, and citations. Do **not** produce a mechanical template. Do **not** \
dump raw memory content; synthesise.

The wiki is the durable record of how this project works AND of every task done on it. \
Pages of kind `adr` are the canonical task-record format — every completed task gets \
one, structured so a future reader can reconstruct: what triggered the work, what \
constraints applied, how it was solved, what was delivered, and what it enables. Pages \
of kind `reference` / `explanation` cover stable scopes (architecture, services, api, \
data-flow, operations) so a reader opening the wiki cold can understand the codebase \
end-to-end.

# Output format

Output **only** the wiki page body, starting with YAML frontmatter, then the body. No \
preamble, no explanation, no surrounding fences.

# Frontmatter (required)

```yaml
---
title: <short specific title — not "Reference: X", just "X">
kind: {kind}
domain: {domain}
status: seedling
authored_by: Opus 4.7
created: {today}
last_reviewed: {today}
audience: [developer, ...]
---
```

# Required structural sections

{kind_specific_sections}

# Conventions

- Write authoritative declarative prose. No filler ("It's worth noting that..."). \
State facts directly.
- When a number is given, name its source ("p50 latency 125ms — measured in \
benchmarks/longmemeval/run_benchmark.py 2026-04").
- When the topic has biological inspiration, name the paper that motivated the design.
- Don't repeat what's already in [[reference/{domain}/architecture-overview]] — link \
to it.
- Each diagram must add information that the table or prose cannot convey efficiently.
- No phrases like "in this section we will" — just say it.
{redaction_conventions}
- Mandatory elements means *constraints*, not steps. A constraint says "MUST honour \
X"; a step says "did X".

# The cluster

**Topic**: {topic}
**Suggested wiki path**: {suggested_path}
**Suggested kind**: {kind}
**Domain**: {domain}
**Memory count**: {n_memories}
**Top entities in cluster**: {entities}

**Existing related wiki pages** (for cross-linking via `[[path]]`):
{related_pages_block}

**Memories in this cluster** (synthesise — do not dump):

{memories_block}

---

Author the wiki page now. Output only the Markdown body, frontmatter first.
"""


WIKI_COVERAGE_PROMPT = """You are Opus 4.7 authoring a structural wiki page for the \
Cortex persistent-memory MCP server.

This is a **coverage-driven** job, not a cluster-driven one: the auto-curator found \
that the project `{domain}` has no substantive page for the scope `{scope_name}` \
("{scope_title}"), and the wiki contract says every project must document this scope. \
Author the page from the source tree, the existing related pages, and any memories \
provided.

# What this scope is

{scope_description}

# Output format

Output **only** the wiki page body, starting with YAML frontmatter, then the body. No \
preamble, no explanation, no surrounding fences.

# Frontmatter (required)

```yaml
---
title: <short specific title — e.g. "{scope_title}: {domain}">
kind: {kind}
domain: {domain}
status: seedling
authored_by: Opus 4.7
created: {today}
last_reviewed: {today}
audience: [developer, ...]
scope: {scope_name}
---
```

# Required structural sections (in this order)

1. **# <title>** — H1 matching frontmatter title.
2. **Lead paragraph** — one paragraph that states the scope of this page and what a \
reader will learn.
3. **Body sections** specific to the scope. For:
   - `architecture` — layers + dependency rule + a Mermaid diagram of the major \
subsystems; cite the directories that map to each layer.
   - `services` — table or list of every major component / handler / module, with \
one-line responsibility statements and the file paths that define each.
   - `api` — exhaustive enumeration of the public surface (CLI flags, HTTP endpoints, \
MCP tools, library functions) with one-line semantics and a stability flag.
   - `data-flow` — a Mermaid sequence or flow diagram of one record's lifecycle \
through the system, with prose explaining each hop and the file that performs it.
   - `operations` — how to deploy, monitor, and recover. Triggers → diagnosis → \
recovery → rollback. Failure modes with symptoms.
4. **## See also** — cross-links to related pages using `[[wiki/path]]` notation.
5. **## Source files** — the files in the codebase a reader should open to verify what \
this page says. Full paths.

# Conventions
{redaction_conventions}

- Walk the source tree if you need to ground the content; the wiki must reflect the \
codebase as it is, not as it was.
- When a number is given, name its source.
- Don't invent components that don't exist in the repo.
- If a scope has nothing yet (e.g. the project has no HTTP API), say so explicitly \
with a one-paragraph "currently none" page rather than fabricating endpoints.

# The job

**Domain**: {domain}
**Scope**: {scope_name} — {scope_title}
**Suggested wiki path**: {suggested_path}
**Suggested kind**: {kind}

**Existing related wiki pages** (for cross-linking via `[[path]]`):
{related_pages_block}

**Supporting memories** (use as ground truth where they exist; otherwise consult the \
source tree):

{memories_block}

---

Author the wiki page now. Output only the Markdown body, frontmatter first.
"""


def _memories_block(
    contents: list[str], tags: list[list[str]], cap: int = MAX_MEMORIES_PER_PROMPT
) -> str:
    """Format a list of memory contents as labelled markdown sub-sections.

    Each memory is capped at 1200 chars to keep the prompt within budget
    while preserving enough context for the LLM to synthesise. The cap
    is generous — a curated cluster of 20 memories at full size would
    blow the context window of even Opus 4.7.
    """
    capped = contents[:cap]
    mem_blocks: list[str] = []
    for idx, content in enumerate(capped, 1):
        t = tags[idx - 1] if idx - 1 < len(tags) else []
        head = content[:_MEMORY_HEAD_CHARS].rstrip()
        if len(content) > _MEMORY_HEAD_CHARS:
            head += "\n...[memory truncated, full content available via recall]"
        tag_str = ", ".join(t) if t else "(no tags)"
        mem_blocks.append(f"### Memory {idx} (tags: {tag_str})\n\n{head}")
    return "\n\n".join(mem_blocks) if mem_blocks else "(none — cluster filtered out)"


def _related_block(related_pages: list[str]) -> str:
    if not related_pages:
        return "(none yet — this is a fresh topic)"
    return "\n".join(f"- [[{p}]]" for p in related_pages)


def _kind_specific_sections(kind: str) -> str:
    """Return the structural-sections instructions for the given kind.

    ADR / task-record pages get the Entry/Mandatory/How/Result/Serves
    requirement; everything else gets the generic Diátaxis-shaped
    explanation/reference structure.
    """
    if kind == "adr":
        return _ADR_TASK_RECORD_SECTIONS
    return _GENERIC_STRUCTURE_SECTIONS


def build_authoring_prompt(
    cluster: CurationCluster,
    related_pages: list[str],
    today: str = "",
) -> str:
    """Construct the structured prompt for an LLM to author the cluster's page.

    The prompt encodes the same conventions the hand-authored 2026-05-17
    pages followed. Returning the prompt as a string (vs. calling an LLM
    here) keeps this module pure and lets the caller pick the LLM
    integration: ``curate_wiki`` returns the prompts for the in-session
    LLM, or a future ``llm_client.author_page(prompt)`` adapter sends
    them directly to the Anthropic API.

    ADR clusters get the task-record section block (Entry / Mandatory /
    How / Result / Serves) — this is how every completed task becomes a
    durable causal record.
    """
    today = today or "2026-05-18"
    return WIKI_AUTHORING_PROMPT.format(
        redaction_conventions=REDACTION_CONVENTIONS,
        kind=cluster.suggested_kind,
        domain=cluster.domain,
        today=today,
        topic=cluster.topic,
        suggested_path=cluster.suggested_path,
        n_memories=len(cluster.memory_ids),
        entities=", ".join(cluster.entities[:8]) or "(none extracted)",
        related_pages_block=_related_block(related_pages),
        memories_block=_memories_block(cluster.memory_contents, cluster.memory_tags),
        kind_specific_sections=_kind_specific_sections(cluster.suggested_kind),
    )


def build_coverage_prompt(
    scope_name: str,
    scope_title: str,
    scope_description: str,
    suggested_kind: str,
    suggested_path: str,
    domain: str,
    related_pages: list[str],
    supporting_memories: list[str],
    supporting_tags: list[list[str]],
    today: str = "",
) -> str:
    """Prompt for a coverage-driven job (missing structural scope).

    Coverage-driven jobs ask the LLM to author the architecture /
    services / api / data-flow / operations page that *should* exist
    for a project but doesn't. Unlike cluster-driven jobs, the memory
    set is small or empty — the LLM is expected to consult the source
    tree to ground the page.
    """
    today = today or "2026-05-18"
    return WIKI_COVERAGE_PROMPT.format(
        redaction_conventions=REDACTION_CONVENTIONS,
        scope_name=scope_name,
        scope_title=scope_title,
        scope_description=scope_description,
        kind=suggested_kind,
        suggested_path=suggested_path,
        domain=domain,
        today=today,
        related_pages_block=_related_block(related_pages),
        memories_block=_memories_block(supporting_memories, supporting_tags),
    )


def build_jobs(
    clusters: list[CurationCluster],
    existing_pages_by_topic: dict[str, list[str]] | None = None,
    today: str = "",
) -> list[CurationJob]:
    """Pair each cluster with its authoring prompt and any related pages."""
    existing_pages_by_topic = existing_pages_by_topic or {}
    jobs: list[CurationJob] = []
    for cl in clusters:
        related = _find_related_pages(cl, existing_pages_by_topic)
        prompt = build_authoring_prompt(cl, related, today=today)
        jobs.append(CurationJob(cluster=cl, prompt=prompt, related_pages=related))
    return jobs


WIKI_REAUTHOR_PROMPT = """You are Opus 4.7 re-authoring an existing wiki page for the \
Cortex persistent-memory MCP server.

The auto-curator detected drift between this page and the codebase. Your job is to \
refine, verify, and update the existing page so it once again matches the current \
source tree. Preserve every accurate claim; replace stale ones; fill gaps; do NOT \
delete sections the author wrote unless they are demonstrably false.

# What drifted

{drift_summary}

# Your task

Re-author the page in Markdown so:

1. Every cited source file path resolves to an actual file in the codebase. Replace \
moved paths with current ones; remove citations of deleted files only when the \
referenced behaviour no longer exists; otherwise update to the new file path.
2. The body matches the current code behaviour — read the cited files (and any new \
files that have appeared in the same module) before rewriting.
3. Required sections for kind `{kind}` are present and substantive. For `adr`: Status, \
Entry, Mandatory elements, How, Result, Serves, Alternatives, References.
4. Update the frontmatter `updated:` field to today, and `last_reviewed: {today}`.

# Output format

Output ONLY the wiki page body, starting with YAML frontmatter, then the body. No \
preamble, no surrounding fences, no explanation.

# Existing page (for context — synthesise, do not blindly copy)

```markdown
{existing_body}
```

# Conventions
{redaction_conventions}

- Same conventions as a fresh authoring job: authoritative declarative prose, \
citations with full paths, mermaid diagrams where dataflow benefits from one, no \
filler phrases.
- "Refine and verify and update" means: cross-check claims against the current source. \
If a paragraph says "implemented via X" and X no longer exists, the paragraph is wrong \
— rewrite it from what actually exists.
- If the page covers a removed feature in its entirety, do NOT silently delete the \
page. Instead, prefix the title with "(deprecated)" and add a one-paragraph note \
pointing to whatever replaced it. Pages with historical value stay.

# The job

**Wiki page**: `{wiki_path}`
**Kind**: {kind}
**Domain**: {domain}
**Existing `updated`**: {last_updated}
**Drift reasons**: {reasons}
**Source root for verification**: {source_root}

---

Re-author the page now. Output only the Markdown body, frontmatter first.
"""


@dataclass
class ReauthorJob:
    """One re-authoring task for an existing wiki page.

    Produced by ``build_reauthor_jobs`` from drift records. Shares the
    wire shape of CurationJob / CoverageJob so the handler serialises
    all three with one helper.
    """

    wiki_path: str
    domain: str
    kind: str
    reasons: list[str]
    prompt: str
    cited_source_files: list[str] = field(default_factory=list)
    missing_source_files: list[str] = field(default_factory=list)


def build_reauthor_prompt(
    drift,
    existing_body: str,
    source_root: str | None,
    today: str = "",
) -> str:
    """Build the LLM prompt for a single drift case."""
    today = today or "2026-05-18"
    drift_lines: list[str] = []
    for r in drift.reasons:
        if r == "missing_source_file":
            missing = ", ".join(drift.missing_source_files[:5]) or "(none listed)"
            drift_lines.append(
                f"- **Missing source files** — the page cites these but they "
                f"don't exist under the current source root: {missing}"
            )
        elif r == "stale_content":
            drift_lines.append(
                f"- **Stale content** — page mtime is {drift.age_days:.0f} days "
                "old and the page cites source files that may have changed."
            )
        elif r == "off_template":
            drift_lines.append(
                f"- **Off-template** — the body is missing one or more sections "
                f"required for kind `{drift.kind}`. Restore the canonical structure."
            )
    summary = "\n".join(drift_lines) if drift_lines else "(none recorded)"

    return WIKI_REAUTHOR_PROMPT.format(
        redaction_conventions=REDACTION_CONVENTIONS,
        drift_summary=summary,
        wiki_path=drift.wiki_path,
        kind=drift.kind or "explanation",
        domain=drift.domain,
        last_updated=drift.last_updated or "(unknown)",
        reasons=", ".join(drift.reasons),
        source_root=source_root or "(unresolved — verify against memory + repo)",
        existing_body=existing_body[:_EXISTING_BODY_CHARS]
        + ("\n…[truncated]" if len(existing_body) > _EXISTING_BODY_CHARS else ""),
        today=today,
    )


def build_reauthor_jobs(
    drifts: list,
    wiki_root: str,
    source_root_resolver,
    today: str = "",
) -> list[ReauthorJob]:
    """Build authoring jobs for every drifted page.

    ``source_root_resolver`` is a callable ``domain -> str | None``
    (matches ``wiki_coverage._project_source_root``). Returns jobs in
    input order — callers can sort by reason severity if desired.
    """
    import os as _os

    jobs: list[ReauthorJob] = []
    for d in drifts:
        full = _os.path.join(wiki_root, d.wiki_path)
        try:
            with open(full, encoding="utf-8", errors="ignore") as fp:
                text = fp.read()
        except OSError:
            continue
        src_root = source_root_resolver(d.domain) if d.domain else None
        prompt = build_reauthor_prompt(d, text, src_root, today=today)
        jobs.append(
            ReauthorJob(
                wiki_path=d.wiki_path,
                domain=d.domain,
                kind=d.kind,
                reasons=list(d.reasons),
                prompt=prompt,
                cited_source_files=list(d.cited_source_files),
                missing_source_files=list(d.missing_source_files),
            )
        )
    return jobs


@dataclass
class CoverageJob:
    """One coverage-driven authoring task.

    A coverage job exists when a project (domain) is missing a page for
    a canonical structural scope (architecture / services / api /
    data-flow / operations / decisions). The downstream LLM authors the
    missing page from the source tree and any supporting memories.

    Coverage jobs share the wire shape of ``CurationJob`` so the handler
    serialises them uniformly. They differ in semantics: a coverage job
    is *structural* (something every project needs) while a curation
    job is *empirical* (this is what the user has been working on).
    """

    domain: str
    scope_name: str
    scope_title: str
    suggested_kind: str
    suggested_path: str
    prompt: str
    related_pages: list[str] = field(default_factory=list)
    supporting_memory_ids: list[int] = field(default_factory=list)


def build_coverage_jobs(
    coverages: list,
    existing_pages_by_topic: dict[str, list[str]] | None = None,
    supporting_memories_by_domain: dict[str, list[dict]] | None = None,
    today: str = "",
) -> list[CoverageJob]:
    """Build authoring jobs for every missing scope across every audited domain.

    Inputs:
      * ``coverages`` — list of ``DomainCoverage`` from
        ``mcp_server.core.wiki_coverage.audit_all_domains``.
      * ``existing_pages_by_topic`` — index used to suggest cross-links
        (same shape as for ``build_jobs``).
      * ``supporting_memories_by_domain`` — optional map of domain →
        memories the LLM can use to ground the scope page. Coverage
        jobs work even with no memories (the LLM consults source);
        memories are a lift when available.

    Returns coverage jobs sorted so the most structurally primary
    scopes (architecture first, decisions last) are authored ahead of
    derived ones — a reader benefits most from architecture being
    written before services, which must be written before api, etc.
    """
    existing_pages_by_topic = existing_pages_by_topic or {}
    supporting_memories_by_domain = supporting_memories_by_domain or {}
    jobs: list[CoverageJob] = []
    for cov in coverages:
        domain = cov.domain
        mems = supporting_memories_by_domain.get(domain, [])
        mem_contents = [m.get("content") or "" for m in mems[:MAX_MEMORIES_PER_PROMPT]]
        mem_tags = [m.get("tags") or [] for m in mems[:MAX_MEMORIES_PER_PROMPT]]
        mem_ids = [m["id"] for m in mems if "id" in m]
        for missing in cov.missing_scopes():
            scope = missing.scope
            related = _find_related_pages_for_scope(
                domain, scope.name, existing_pages_by_topic
            )
            prompt = build_coverage_prompt(
                scope_name=scope.name,
                scope_title=scope.title,
                scope_description=scope.description,
                suggested_kind=scope.suggested_kind,
                suggested_path=missing.suggested_path,
                domain=domain,
                related_pages=related,
                supporting_memories=mem_contents,
                supporting_tags=mem_tags,
                today=today,
            )
            jobs.append(
                CoverageJob(
                    domain=domain,
                    scope_name=scope.name,
                    scope_title=scope.title,
                    suggested_kind=scope.suggested_kind,
                    suggested_path=missing.suggested_path,
                    prompt=prompt,
                    related_pages=related,
                    supporting_memory_ids=mem_ids,
                )
            )
    return jobs


# Order of structural primacy — architecture first so a reader can
# anchor every other scope against it. ``decisions`` last because it
# accumulates organically from task-records.
_SCOPE_PRIMACY: dict[str, int] = {
    "architecture": 0,
    "services": 1,
    "api": 2,
    "data-flow": 3,
    "operations": 4,
    "decisions": 5,
}


def sort_coverage_jobs(jobs: list[CoverageJob]) -> list[CoverageJob]:
    """Return ``jobs`` sorted by (scope primacy, domain) so the most
    foundational scopes are authored first.
    """
    return sorted(
        jobs,
        key=lambda j: (_SCOPE_PRIMACY.get(j.scope_name, 99), j.domain),
    )


def _find_related_pages_for_scope(
    domain: str,
    scope_name: str,
    existing_pages_by_topic: dict[str, list[str]],
) -> list[str]:
    """Find existing wiki pages that mention the domain or the scope name.

    Coverage pages benefit from cross-linking to the project's existing
    pages so the new page integrates rather than floating alone.
    """
    keys = {domain.lower(), scope_name.lower()}
    related: list[str] = []
    seen: set[str] = set()
    for topic, paths in existing_pages_by_topic.items():
        t = topic.lower()
        if any(k in t for k in keys):
            for p in paths:
                if p not in seen:
                    related.append(p)
                    seen.add(p)
    return related[:6]


def _find_related_pages(
    cluster: CurationCluster,
    existing_pages_by_topic: dict[str, list[str]],
) -> list[str]:
    """Find existing wiki pages whose topic words overlap with this cluster's."""
    related: list[str] = []
    topic_tokens = set(re.findall(r"[a-z0-9]+", cluster.topic.lower()))
    topic_tokens.update(re.findall(r"[a-z0-9]+", " ".join(cluster.entities).lower()))
    seen: set[str] = set()
    for existing_topic, paths in existing_pages_by_topic.items():
        et_tokens = set(re.findall(r"[a-z0-9]+", existing_topic.lower()))
        if topic_tokens & et_tokens:
            for p in paths:
                if p not in seen and p != cluster.suggested_path:
                    related.append(p)
                    seen.add(p)
    return related[:6]
