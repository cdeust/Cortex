"""Bootstrap seed data for the wiki axis registry — pure data, no logic.

Extracted from ``wiki_axis_registry.py`` (issue #134, file exceeded the
500-line hard limit in coding-standards.md §4). Holds the default
``AxisValue`` entries for every axis (kind, lifecycle, audience,
provenance) that seed the registry before any user ``wiki/_schema/``
overrides are applied. See ``wiki_axis_registry.py`` for the
``AxisValue``/``AxisRegistry`` data model and registry-construction
mechanics that consume this data.
"""

from __future__ import annotations

import re

from mcp_server.core.wiki_axis_registry import (
    AXIS_AUDIENCE,
    AXIS_KIND,
    AXIS_LIFECYCLE,
    AXIS_PROVENANCE,
    AxisValue,
)


def _re(pattern: str) -> re.Pattern[str]:
    """Compile a regex with IGNORECASE — every axis pattern is case-insensitive."""
    return re.compile(pattern, re.IGNORECASE)


def _re_ml(pattern: str) -> re.Pattern[str]:
    """Compile a regex with IGNORECASE + MULTILINE for ``^``-anchored line patterns."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE)


# Each tuple = (name, display_name, patterns, tag_aliases, kwargs).
DEFAULT_KINDS: tuple[AxisValue, ...] = (
    AxisValue(
        name="adr",
        axis=AXIS_KIND,
        display_name="ADR (Architecture Decision Record)",
        patterns=(
            # Inline decision markers (Nygard prose).
            _re(r"\b(decided to|decision:|the decision is|chose .+ because)\b"),
            _re(r"\b(rejected .+ (due to|because)|we will use|selected .+ over)\b"),
            # Nygard heading skeleton — the canonical ADR section structure.
            # Pilot 2026-05-13 found that 3 of 8 sampled ADRs had ``## Decision``
            # heading without a colon, so the prose-only patterns missed them.
            _re_ml(r"^##+\s*Decision\s*$"),
            _re_ml(r"^##+\s*Consequences\s*$"),
        ),
        # ``architecture`` removed (pilot 2026-05-13): it is too broad to be an
        # ADR-only tag — 8 of 8 sampled rfc/ pages were misrouted to adr/
        # because they carried the ``architecture`` tag. Architecture-tagged
        # content is more often spec/rfc/explanation than a single decision.
        tag_aliases=("decision", "adr"),
        description="Nygard/MADR-style record of a single architectural decision.",
    ),
    AxisValue(
        name="tutorial",
        axis=AXIS_KIND,
        display_name="Tutorial",
        patterns=(
            _re(
                r"\b(tutorial:|in this tutorial|"
                r"we['']?ll (learn|build|create|walk through))\b"
            ),
            _re(r"\b(by the end of this tutorial|getting started:|step 1[:.])\b"),
        ),
        tag_aliases=("tutorial", "getting-started"),
        description="Learn-by-doing walkthrough (Diátaxis).",
    ),
    AxisValue(
        name="how-to",
        axis=AXIS_KIND,
        display_name="How-to guide",
        patterns=(_re(r"\b(how to |how do (you|i) |here['']?s how to )\b"),),
        tag_aliases=("how-to", "howto", "guide"),
        description="Task-oriented recipe for a known goal (Diátaxis / DITA task).",
    ),
    AxisValue(
        name="reference",
        axis=AXIS_KIND,
        display_name="Reference",
        patterns=(),  # reference is usually identified by tags / producer, not content
        # Producer audit (ADR-2244 Phase 6): ``codebase`` is the bare tag
        # written by ``codebase_analyze``; without it here, file-doc pages
        # got routed to ``explanation`` instead of ``reference``, producing
        # the 8734-page misroute Phase 4.2 had to clean up.
        tag_aliases=("reference", "api", "spec", "code-reference", "codebase"),
        description="Authoritative lookup table — API docs, file docs, schema refs.",
    ),
    AxisValue(
        name="explanation",
        axis=AXIS_KIND,
        display_name="Explanation",
        patterns=(
            _re(r"\b(what is|why does|the reason|conceptually|under the hood)\b"),
            # Lesson-shaped content collapses into explanation per ADR-2244 §4.1.
            _re(r"\b(the bug was|root cause|lesson learned|fix:|fixed by)\b"),
            # Convention-shaped content also collapses into explanation.
            _re(r"\b(always use|never |the canonical|convention:|rule:|standard:)\b"),
        ),
        tag_aliases=(
            "explanation",
            "concept",
            "lesson",
            "convention",
            "rule",
            "standard",
        ),
        description="Concept-oriented prose explaining the 'why' (Diátaxis).",
    ),
    AxisValue(
        name="runbook",
        axis=AXIS_KIND,
        display_name="Runbook",
        patterns=(
            _re(r"\b(runbook|incident response|on[- ]call|when (the )?alert fires)\b"),
            _re(r"\b(if (this|that) happens|recovery procedure|rollback steps?)\b"),
        ),
        tag_aliases=("runbook", "playbook", "incident", "oncall"),
        description="SRE incident-response procedure (Rootly/Squadcast convention).",
    ),
    AxisValue(
        name="rfc",
        axis=AXIS_KIND,
        display_name="RFC (Request For Comments)",
        patterns=(
            _re(
                r"\b(rfc:|proposal:|we propose to|proposed (design|change|approach))\b"
            ),
            _re(r"\b(this rfc|request for comments)\b"),
        ),
        tag_aliases=("rfc", "proposal", "spec", "design"),
        description="Pre-decision design proposal open for comment (IETF/arc42 §4).",
    ),
    AxisValue(
        name="journal",
        axis=AXIS_KIND,
        display_name="Journal entry",
        patterns=(
            _re(r"^##?\s*\d{4}-\d{2}-\d{2}\b"),  # dated H1/H2 header
        ),
        tag_aliases=("journal", "diary", "log"),
        description="Dated reflective entry — digital-garden / Confluence blog style.",
    ),
)


DEFAULT_LIFECYCLES: tuple[AxisValue, ...] = (
    AxisValue(
        name="seedling",
        axis=AXIS_LIFECYCLE,
        display_name="Seedling",
        default=True,  # default for new non-ADR pages
        patterns=(_re(r"_to be (filled|written)_"),),
        tag_aliases=("seedling", "seed", "new", "stub"),
        description="Initial stub, expected to grow (digital-garden convention).",
    ),
    AxisValue(
        name="draft",
        axis=AXIS_LIFECYCLE,
        display_name="Draft",
        patterns=(_re(r"\bdraft\b"),),
        tag_aliases=("draft", "wip"),
        description="Work in progress, not yet published.",
    ),
    AxisValue(
        name="active",
        axis=AXIS_LIFECYCLE,
        display_name="Active",
        patterns=(),
        tag_aliases=("active", "current", "live"),
        description="Maintained and authoritative.",
    ),
    AxisValue(
        name="deprecated",
        axis=AXIS_LIFECYCLE,
        display_name="Deprecated",
        patterns=(_re(r"\bdeprecated\b"),),
        tag_aliases=("deprecated", "legacy"),
        description="Still readable, but new use should prefer the replacement.",
    ),
    AxisValue(
        name="archived",
        axis=AXIS_LIFECYCLE,
        display_name="Archived",
        patterns=(_re(r"\barchived\b"),),
        tag_aliases=("archived", "historic"),
        description="Frozen historical record; do not modify.",
    ),
    # ADR-specific lifecycle subset (Nygard / MADR).
    AxisValue(
        name="proposed",
        axis=AXIS_LIFECYCLE,
        display_name="Proposed (ADR)",
        default=True,  # default for new ADRs
        applies_to_kinds=("adr",),
        patterns=(_re(r"\bproposed\b"),),
        tag_aliases=("proposed",),
        description="ADR awaiting decision (Nygard).",
    ),
    AxisValue(
        name="accepted",
        axis=AXIS_LIFECYCLE,
        display_name="Accepted (ADR)",
        applies_to_kinds=("adr",),
        patterns=(_re(r"\baccepted\b"),),
        tag_aliases=("accepted",),
        description="ADR adopted and in effect (Nygard).",
    ),
    AxisValue(
        name="rejected",
        axis=AXIS_LIFECYCLE,
        display_name="Rejected (ADR)",
        applies_to_kinds=("adr",),
        patterns=(_re(r"\brejected\b"),),
        tag_aliases=("rejected",),
        description="ADR considered and dismissed (Nygard).",
    ),
    AxisValue(
        name="superseded",
        axis=AXIS_LIFECYCLE,
        display_name="Superseded (ADR)",
        applies_to_kinds=("adr",),
        patterns=(_re(r"\bsuperseded\b"),),
        tag_aliases=("superseded",),
        description="ADR replaced by a later one (Nygard).",
    ),
)


DEFAULT_AUDIENCES: tuple[AxisValue, ...] = (
    AxisValue(
        name="developer",
        axis=AXIS_AUDIENCE,
        display_name="Developer",
        default=True,
        patterns=(
            _re(r"\b(function|class|method|import|module|API|SDK|library|interface)\b"),
        ),
        tag_aliases=("dev", "developer", "engineer", "code"),
        description="Software engineers writing or modifying code.",
    ),
    AxisValue(
        name="ops",
        axis=AXIS_AUDIENCE,
        display_name="Operations / SRE",
        patterns=(
            _re(
                r"\b(deploy(ment)?|kubernetes|terraform|infra(structure)?|cluster|node|pod)\b"
            ),
            _re(r"\b(sre|on[- ]call|incident|alert|monitoring|observability)\b"),
        ),
        tag_aliases=("ops", "sre", "infra", "deploy", "k8s"),
        description="Operators of production systems.",
    ),
    AxisValue(
        name="security",
        axis=AXIS_AUDIENCE,
        display_name="Security",
        # Pilot 2026-05-13 found bare ``crypto`` (Node built-in module) false-
        # positiving as a security signal. The patterns now require the full
        # suffix (``cryptograph(y|ic)``) or the longer security-domain words.
        # Same for ``auth`` — must be ``authentication``/``authorization`` to
        # count, not the abbreviation.
        patterns=(
            _re(
                r"\b(authentication|authorization|cryptograph(y|ic)|"
                r"vulnerab(le|ility)|cve|threat model)\b"
            ),
            _re(
                r"\b(credential|oauth|sso|encryption|decrypt(ed|ion)?|"
                r"key rotation|HSM|secret manager)\b"
            ),
        ),
        # Tags remain the strongest signal — a page explicitly tagged ``security``
        # is unambiguous.
        tag_aliases=("security", "auth", "crypto", "vulnerability", "secops"),
        description="Security engineers and reviewers.",
    ),
    AxisValue(
        name="internal",
        axis=AXIS_AUDIENCE,
        display_name="Internal",
        patterns=(),
        tag_aliases=("internal", "private"),
        description="Internal team-only content (not for external publication).",
    ),
    AxisValue(
        name="external",
        axis=AXIS_AUDIENCE,
        display_name="External",
        patterns=(),
        tag_aliases=("external", "public", "customer"),
        description="External-facing documentation for users / customers.",
    ),
)


DEFAULT_PROVENANCES: tuple[AxisValue, ...] = (
    AxisValue(
        name="human",
        axis=AXIS_PROVENANCE,
        display_name="Human-authored",
        default=True,
        patterns=(),
        tag_aliases=("human", "authored"),
        description="Hand-written by a person.",
    ),
    AxisValue(
        name="ai-generated",
        axis=AXIS_PROVENANCE,
        display_name="AI-generated",
        patterns=(),
        tag_aliases=("ai-generated", "synthesized", "synth"),
        requires_generator=True,
        description="Produced by an LLM via a template prompt.",
    ),
    AxisValue(
        name="imported",
        axis=AXIS_PROVENANCE,
        display_name="Imported",
        patterns=(),
        tag_aliases=("imported", "import"),
        description="Bulk-imported from an external memory system.",
    ),
    AxisValue(
        name="auto-generated",
        axis=AXIS_PROVENANCE,
        display_name="Auto-generated (codebase)",
        patterns=(),
        tag_aliases=("auto-generated", "code-reference", "codebase"),
        requires_generator=True,
        description="Produced by ``codebase_analyze`` / ``wiki_seed_codebase``.",
    ),
)


ALL_DEFAULTS: tuple[AxisValue, ...] = (
    DEFAULT_KINDS + DEFAULT_LIFECYCLES + DEFAULT_AUDIENCES + DEFAULT_PROVENANCES
)
