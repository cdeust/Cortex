"""MCP prompts for Cortex — ``prompts/list`` + ``prompts/get`` (issue #176).

Cortex registers ~51 tools but exposes no prompts, so every multi-tool
workflow it supports is discoverable only by reading docs or guessing — and
those are exactly the compositions where a caller gets the order wrong
(promotion episodic→semantic, wiki curation, session recall/onboarding). This
module publishes those compositions as protocol the client can enumerate.

Source of truth (issue #176 criterion 3, the #98 drift class): a prompt step
names a tool and pulls that tool's one-line summary from the SAME handler
schema map (``SCHEMAS``) that ``tools/list`` is built from — never a second,
hand-maintained copy that can drift. ``test_mcp_prompts`` asserts every step
tool exists in that map.

Profile awareness (issue #177): ``is_available`` decides whether a prompt is
offered under a profile — a prompt is offered iff the profile registers every
tool its workflow drives. So ``session_recall`` (all-lean tools) is offered in
both profiles, while ``promote_memories`` and ``curate_wiki`` (which drive the
full curation/consolidation surface) are hidden AND gated under ``lean`` by
``ToolProfileMiddleware``.

Per-argument ``title``: the installed MCP SDK models a prompt argument as
``name``/``description``/``required`` only (``mcp.types.PromptArgument`` has no
``title`` field in this protocol version), so the human title is folded into
each argument's description rather than emitted as a separate field. The
prompt-level ``title`` IS emitted.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated

from pydantic import Field

from mcp_server.tool_profiles import ToolProfile, allows

if TYPE_CHECKING:  # pragma: no cover - typing only
    from mcp.server.mcpserver import MCPServer


@dataclass(frozen=True)
class _Step:
    tool: str
    guidance: str


@dataclass(frozen=True)
class _Spec:
    name: str
    title: str
    description: str
    steps: tuple[_Step, ...]
    closing: str


# ── Prompt catalog ──────────────────────────────────────────────────────────
# Each step's tool must exist in the merged handler SCHEMAS (asserted by test).

SESSION_RECALL = _Spec(
    name="session_recall",
    title="Session recall / onboarding",
    description="Onboard onto a project and recall what Cortex already knows about it.",
    steps=(
        _Step(
            "query_methodology",
            "Load the cognitive profile + hot memories for this project first.",
        ),
        _Step(
            "recall",
            "Pull memories relevant to your focus via the 6-signal WRRF fusion.",
        ),
        _Step(
            "unified_search",
            "Widen to memories + wiki + code in one pass when recall is thin.",
        ),
        _Step(
            "recall_hierarchical",
            "Zoom out to fractal L0/L1/L2 clusters for the shape, not just hits.",
        ),
        _Step(
            "memory_stats",
            "Sanity-check store health and coverage before trusting a sparse result.",
        ),
    ),
    closing=(
        "Absence from recall is not proof of absence — memory decays; widen with "
        "unified_search or lower thresholds before concluding nothing is stored."
    ),
)

PROMOTE_MEMORIES = _Spec(
    name="promote_memories",
    title="Promote episodic memories to semantic",
    description="Consolidate episodic memories into durable semantic knowledge (CLS).",
    steps=(
        _Step(
            "consolidate",
            "Run the maintenance cycle — this drives CLS episodic→semantic "
            "abstraction.",
        ),
        _Step(
            "memory_stats",
            "Read what consolidation moved: stage counts, semantic vs episodic.",
        ),
        _Step(
            "curate_distill",
            "Pull understanding-level dossiers (error→success, co-access, "
            "entity family) to author lessons from.",
        ),
        _Step(
            "remember",
            "Write each distilled insight back as a `lesson` memory so it "
            "survives as semantic knowledge.",
        ),
    ),
    closing=(
        "curate_distill returns source material for lesson authoring, not memories — "
        "do not treat its dossiers as stored. Cite concrete entities in each lesson so "
        "synaptic tagging can link it to related traces."
    ),
)

CURATE_WIKI = _Spec(
    name="curate_wiki",
    title="Wiki curation kickoff",
    description="Turn a topic's memory + code evidence into a verified "
    "first-class wiki page.",
    steps=(
        _Step(
            "unified_search",
            "Gather the memory + code evidence for the topic before writing.",
        ),
        _Step(
            "curate_wiki",
            "Auto-curate candidate pages from the relevant memory clusters.",
        ),
        _Step(
            "wiki_write",
            "Author or refine the first-class page (ADR/spec/note) from the "
            "curated material.",
        ),
        _Step("wiki_verify", "Verify the page's integrity and links before finishing."),
    ),
    closing=(
        "Curate from evidence, not intuition — every claim on the page should "
        "trace to a memory or code reference you gathered. Verify links so "
        "the page stays navigable."
    ),
)

_SPECS: tuple[_Spec, ...] = (SESSION_RECALL, PROMOTE_MEMORIES, CURATE_WIKI)
_SPEC_BY_NAME: dict[str, _Spec] = {s.name: s for s in _SPECS}

PROMPT_NAMES: tuple[str, ...] = tuple(s.name for s in _SPECS)


def required_tools(prompt_name: str) -> tuple[str, ...]:
    """The tools a prompt's workflow drives, or ``()`` if no such prompt."""
    spec = _SPEC_BY_NAME.get(prompt_name)
    return tuple(step.tool for step in spec.steps) if spec else ()


def is_available(prompt_name: str, profile: ToolProfile) -> bool:
    """Whether ``prompt_name`` is offered under ``profile``.

    A prompt is offered iff it exists and the profile registers every tool its
    workflow drives (mirrors ``ToolProfile.allows`` for tools).
    """
    tools = required_tools(prompt_name)
    return bool(tools) and all(allows(profile, tool) for tool in tools)


def tool_summary(schemas: dict[str, dict], tool: str) -> str:
    """First sentence of ``tool``'s description from the handler schema map.

    Source of truth is ``schemas`` (the same map ``tools/list`` is built from).
    Returns a backticked fallback if the tool or its description is absent.
    """
    description = schemas.get(tool, {}).get("description")
    if not description:
        return f"`{tool}`"
    head, _, _ = description.partition(". ")
    return head + "." if head else description


def _render_body(schemas: dict[str, dict], spec: _Spec, intro: str) -> str:
    lines = [
        intro,
        "",
        "Cortex's tools compose in a specific order; call them out of order and you "
        "get an empty or misleading result, not an error. Work them in this order:",
        "",
    ]
    for i, step in enumerate(spec.steps, start=1):
        lines.append(
            f"{i}. `{step.tool}` — {tool_summary(schemas, step.tool)} {step.guidance}"
        )
    lines += ["", spec.closing]
    return "\n".join(lines)


def register_prompts(mcp: MCPServer, schemas: dict[str, dict]) -> None:
    """Register every prompt on ``mcp``, rendering bodies from ``schemas``.

    Prompts are registered unconditionally; ``ToolProfileMiddleware`` hides and
    gates the ones a ``lean`` session cannot run (``is_available``).
    """
    _register_session_recall(mcp, schemas)
    _register_promote_memories(mcp, schemas)
    _register_curate_wiki(mcp, schemas)


def _register_session_recall(mcp: MCPServer, schemas: dict[str, dict]) -> None:
    @mcp.prompt(
        name=SESSION_RECALL.name,
        title=SESSION_RECALL.title,
        description=SESSION_RECALL.description,
    )
    def session_recall(
        project: Annotated[
            str,
            Field(description="Project — absolute path or project id to onboard onto."),
        ],
        focus: Annotated[
            str,
            Field(description="Optional focus — a topic or question to steer recall."),
        ] = "",
    ) -> str:
        """Guide a recall/onboarding session.

        mcp 2.0.0 migration (PR #331): argument descriptions moved from this
        docstring's Args: section into Annotated[..., Field(description=...)]
        on each parameter — mcp 2.0.0's func_metadata no longer parses
        Google-style docstrings for per-parameter descriptions the way
        FastMCP did (verified: no docstring-parsing logic anywhere in
        mcp.server.mcpserver.utilities.func_metadata, 2026-08-10). The
        docstring itself still supplies the prompt's own description.
        """
        intro = f'Onboard onto project "{project}" and recall what Cortex already knows'
        intro += f" about: {focus}." if focus else "."
        return _render_body(schemas, SESSION_RECALL, intro)


def _register_promote_memories(mcp: MCPServer, schemas: dict[str, dict]) -> None:
    @mcp.prompt(
        name=PROMOTE_MEMORIES.name,
        title=PROMOTE_MEMORIES.title,
        description=PROMOTE_MEMORIES.description,
    )
    def promote_memories(
        scope: Annotated[
            str,
            Field(
                description="Optional scope — a domain or project to bound promotion."
            ),
        ] = "",
    ) -> str:
        """Guide episodic→semantic promotion.

        See session_recall's docstring above for why argument descriptions
        live in Annotated[..., Field(...)] rather than an Args: section.
        """
        intro = "Promote episodic memories into consolidated semantic knowledge"
        intro += f' for scope "{scope}".' if scope else "."
        return _render_body(schemas, PROMOTE_MEMORIES, intro)


def _register_curate_wiki(mcp: MCPServer, schemas: dict[str, dict]) -> None:
    @mcp.prompt(
        name=CURATE_WIKI.name,
        title=CURATE_WIKI.title,
        description=CURATE_WIKI.description,
    )
    def curate_wiki(
        topic: Annotated[
            str, Field(description="Topic — the subject the wiki page should cover.")
        ],
    ) -> str:
        """Guide a wiki curation kickoff.

        See session_recall's docstring above for why argument descriptions
        live in Annotated[..., Field(...)] rather than an Args: section.
        """
        intro = f'Kick off wiki curation for "{topic}".'
        return _render_body(schemas, CURATE_WIKI, intro)
