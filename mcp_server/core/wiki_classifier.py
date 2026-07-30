"""Wiki content classifier — determines page kind or rejects noise.

Pure business logic — no I/O. The sync path calls this to decide
whether a memory should become a wiki page, and what kind.

Classification hierarchy (inspired by Alexander pattern-language P2 + Eco;
the labels are conceptual framing, not a computational result borrowed from
either author):
  1. REJECT: tool invocations, system prompts, JSON, generic instructions
  2. ADR: contains a decision with rationale
  3. LESSON: describes a mistake and its resolution
  4. CONVENTION: establishes a rule or standard
  5. SPEC: describes a feature or system design
  6. NOTE: catch-all for meaningful content

Module split (issue #134, coding-standards.md §4 — this file was 916
lines, over the 500-line hard limit): pattern tables now live in
``wiki_classifier_patterns.py``, the hard-negative/audit/positive-score
gate functions in ``wiki_classifier_gates.py``, title derivation in
``wiki_title.py``, and ADR-2244 modern-kind/lifecycle/audience/provenance
detection in ``wiki_kind_detection.py``. This module keeps the admission
orchestration (``_classify_to_legacy_kind``), the user-rules provider
(reverse-DI port, kept here because tests monkeypatch its module-level
globals directly), and the public ``classify_memory`` entry point.
``derive_title`` is re-exported for backward-compatible imports.
"""

from __future__ import annotations

from typing import Callable

from mcp_server.core.wiki_classifier_gates import (
    fails_audit_tag_gate,
    fails_hard_negatives,
    positive_score,
)
from mcp_server.core.wiki_classifier_patterns import (
    ADR_PATTERNS,
    CONVENTION_PATTERNS,
    LESSON_PATTERNS,
    POSITIVE_SCORE_THRESHOLD,
    REJECT_PATTERNS,
    REJECT_PREFIXES,
    REJECT_TITLES,
    SPEC_TAGS,
)
from mcp_server.core.wiki_kind_detection import (
    detect_audiences,
    detect_modern_kind,
    detect_provenance,
    pick_lifecycle,
)
from mcp_server.core.wiki_title import derive_title, slugify as _slugify
from mcp_server.observability import silent_failure
from mcp_server.core.wiki_rule_engine import apply_rules
from mcp_server.shared.wiki_classification import Classification, Generator
from mcp_server.core.wiki_axis_registry import (
    AXIS_PROVENANCE,
    axis_registry_get,
    get_registry,
)

__all__ = [
    "classify_memory",
    "configure_user_rules_provider",
    "derive_title",
    "reset_user_rules",
]

# ── User-rule integration (Phase 5.1) ─────────────────────────────────
#
# Rules live in ~/.claude/methodology/wiki/_rules/*.md and are loaded
# on demand. Cached in-process; refresh by calling reset_user_rules().
# When no rules are loaded (or the wiki isn't initialised), falls back
# to the hardcoded defaults below.
#
# Reverse DI (issue #126): loading these rules requires reading files
# under the wiki root — that is I/O, and core must not call the
# infrastructure-backed loader (``infrastructure.wiki_schema_reader.
# load_registry``) directly. The composition root
# (``mcp_server/__main__.py``) supplies a zero-arg provider via
# ``configure_user_rules_provider`` once at boot; no provider configured
# falls back to the hardcoded defaults below, same as a load failure.

# Content shorter than this many stripped characters is never admitted as a
# wiki page.
# source: pre-existing tuned value, extracted unchanged (#197 family 3);
# provenance not recorded at introduction
_MIN_ADMISSIBLE_CHARS = 50

# A tagged memory is only promoted to "spec" above this many characters.
# source: the 200–3000 char "atomic scope" band documented in
# wiki_classifier_gates.positive_score — an unsourced engineering default
# for "a self-contained note" (calibration pending)
_MIN_SPEC_CHARS = 200

_USER_RULES_CACHE = None  # None = not loaded; [] = loaded but empty
_USER_RULES_PROVIDER: Callable[[], list] | None = None


def configure_user_rules_provider(provider: Callable[[], list]) -> None:
    """Composition-root injection point: register how to obtain the
    user-editable classifier rules (``wiki/_rules/*.md``, parsed into
    ``ClassifierRule`` objects). Call once at MCP server boot.
    """
    global _USER_RULES_PROVIDER
    _USER_RULES_PROVIDER = provider


def _load_user_rules():
    """Lazy-load + cache user rules. Never raises; returns []."""
    global _USER_RULES_CACHE
    if _USER_RULES_CACHE is not None:
        return _USER_RULES_CACHE
    try:
        _USER_RULES_CACHE = (
            list(_USER_RULES_PROVIDER()) if _USER_RULES_PROVIDER is not None else []
        )
    except Exception as exc:  # noqa: BLE001 — mechanism boundary; failure is observable via silent_failure
        silent_failure.note("wiki_classifier.user_rules_load", exc)
        _USER_RULES_CACHE = []
    return _USER_RULES_CACHE


def reset_user_rules() -> None:
    """Force the next classify_memory call to re-read the rule files.

    Public API — call from a wiki_reload tool when the user edits
    `_rules/*.md` and wants the change to take effect immediately.
    """
    global _USER_RULES_CACHE
    _USER_RULES_CACHE = None


def _apply_user_rules(content: str, tags: list[str] | None):
    """Apply user-loaded rules; return RuleMatch or None when no rule
    matched (caller falls back to hardcoded defaults).

    Returns the RuleMatch dataclass from wiki_rule_engine; the caller
    inspects .target_kind and .matched_rule.
    """
    rules = _load_user_rules()
    if not rules:
        return None

    match = apply_rules(content, tags, rules)
    if match.matched_rule is None:
        return None  # No rule matched — defer to hardcoded defaults
    return match


def _classify_to_legacy_kind(content: str, tags: list[str] | None = None) -> str | None:
    """Run the admission gates and return a legacy kind name or None.

    This is the internal kind-detection used by ``classify_memory``.
    Returns one of {adr, lesson, convention, spec, note} when admitted,
    or None on rejection. The string return is mapped to the ADR-2244
    modern kind by ``classify_memory`` before reaching any caller.

    Internal-only — direct callers should use ``classify_memory`` so they
    receive a full ``Classification`` tuple, not just the kind.
    """
    if not content or len(content.strip()) < _MIN_ADMISSIBLE_CHARS:
        return None

    stripped = content.strip()
    first_line = stripped.split("\n", 1)[0].strip()

    # Gate -1 — Audit-tag gate (runs BEFORE user rules).
    # Session artefacts (backfill, imports, tool output, code reviews,
    # stage reports) are memory-only. They are valuable for recall but
    # noise in the wiki. This runs first because even a user rule that
    # matches "Decision:" should not override the audit-tag disqualifier:
    # backfilled decisions are still backfill, not curated knowledge.
    tag_set_pre = {t.lower() for t in (tags or [])}
    if fails_audit_tag_gate(tag_set_pre):
        return None

    # Gate 0 — User-editable rules (Phase 5.1).
    # If the wiki has rules in `_rules/*.md`, they fire BEFORE the
    # hardcoded defaults so the user can override any built-in
    # admit/reject decision without editing Python.
    user_rule_match = _apply_user_rules(content, tags)
    if user_rule_match is not None:
        if user_rule_match.target_kind in (None, ""):
            return None  # rule says reject
        if user_rule_match.matched_rule and user_rule_match.target_kind:
            return user_rule_match.target_kind  # rule admits with kind

    # Gate 1 — Noise rejection (obvious tool/system/slash artefacts)
    for prefix in REJECT_PREFIXES:
        if stripped.startswith(prefix):
            return None

    for pattern in REJECT_PATTERNS:
        if pattern.match(stripped):
            return None

    slug = _slugify(first_line)
    if slug in REJECT_TITLES:
        return None

    # Gate 2 — Hard-negative gate (task-shape, narration, status, deixis,
    # path/URL titles, audit-shaped titles)
    if fails_hard_negatives(content, first_line):
        return None

    # Tag-based fast-path: explicit knowledge tags bypass positive scoring.
    # The caller has declared intent; trust the declaration.
    # ADR-2244: extended to include the new modern-kind shape tags
    # (runbook/tutorial/how-to/rfc/journal) plus the auto-gen producer
    # markers (code-reference/codebase) so codebase_analyze output is
    # admitted by the gate and the provenance facet downstream marks it
    # as auto-generated.
    tag_set = tag_set_pre
    _EXPLICIT_KNOWLEDGE_TAGS = {
        # Legacy knowledge tags.
        "decision",
        "adr",
        "architecture",
        "spec",
        "design",
        "lesson",
        "convention",
        "rule",
        "standard",
        "paper",
        "research",
        # ADR-2244 modern-kind shape tags.
        "runbook",
        "playbook",
        "tutorial",
        "getting-started",
        "how-to",
        "howto",
        "rfc",
        "proposal",
        "journal",
        # 2026-05-18: ``code-reference`` / ``codebase`` removed from this
        # set — they are audit tags (see ``wiki_classifier_patterns.AUDIT_TAGS``)
        # and rejected at Gate -1, so listing them here was dead code and a
        # footgun. The wiki documents code structurally through scope pages
        # (architecture / services / api / data-flow per project), not
        # via per-file dumps.
    }
    has_explicit_tag = bool(tag_set & _EXPLICIT_KNOWLEDGE_TAGS)

    # Gate 3 — Positive scoring (only when no explicit knowledge tag)
    if not has_explicit_tag:
        if positive_score(content, tag_set) < POSITIVE_SCORE_THRESHOLD:
            return None

    # ─── Admitted — now route to the right kind ──────────────────────

    for pat in ADR_PATTERNS:
        if pat.search(content):
            return "adr"

    if tag_set & {"decision", "adr"}:
        return "adr"

    for pat in LESSON_PATTERNS:
        if pat.search(content):
            return "lesson"

    if tag_set & {"lesson", "debugging", "fix", "bug-fix"}:
        return "lesson"

    for pat in CONVENTION_PATTERNS:
        if pat.search(content):
            return "convention"

    if tag_set & {"convention", "rule", "standard"}:
        return "convention"

    if tag_set & SPEC_TAGS and len(content) > _MIN_SPEC_CHARS:
        return "spec"

    if tag_set & {"architecture", "design"} and len(content) > _MIN_SPEC_CHARS:
        return "spec"

    # Catch-all: meaningful content that passed the gate
    return "note"


# ── ADR-2244 4-tuple classification (Phase 1) ─────────────────────────


def classify_memory(
    content: str,
    tags: list[str] | None = None,
):
    """Classify memory content for the wiki (ADR-2244 single classifier).

    Returns a ``Classification`` (kind, lifecycle, audience, provenance,
    generator, tags) from ``mcp_server.shared.wiki_classification`` when
    the memory should be admitted, or ``None`` to reject.

    **Open-world dispatch.** Every axis consults
    ``mcp_server.core.wiki_axis_registry`` (via ``wiki_kind_detection``) —
    adding a new kind / lifecycle / audience / provenance is a wiki schema
    edit, not a Python edit (user direction 2026-05-12). Detection is
    regex- and tag-driven via ``match_axis``.

    Admission gates (unchanged from the legacy single-kind classifier):
      1. Audit-tag gate — backfill / session-summary / stage-N / tool-output.
      2. User-editable rules from ``wiki/_rules/*.md``.
      3. Noise rejection — tool/system/slash artefacts.
      4. Hard-negative gate — imperatives, first-person, status framing,
         temporal deixis, path/URL titles, audit-shaped titles.
      5. Positive scoring — ≥ 4 of 8 signals, unless an explicit knowledge
         tag bypasses.
    """

    legacy_kind = _classify_to_legacy_kind(content, tags)
    if legacy_kind is None:
        return None

    modern_kind = detect_modern_kind(content, tags, legacy_kind)
    provenance = detect_provenance(tags)
    lifecycle = pick_lifecycle(modern_kind)
    audiences = detect_audiences(content, tags, modern_kind)

    # Provenance with full generator block when the registered provenance
    # requires it. The registry entry's ``requires_generator`` flag is the
    # source of truth — no hardcoded set of provenance names here.
    generator: Generator | None = None

    prov_value = axis_registry_get(get_registry(), AXIS_PROVENANCE, provenance)
    if prov_value is not None and prov_value.requires_generator:
        generator = Generator(
            model="unknown",
            version="",
            prompt_template="",
            generated_at="",
        )

    # Tags pass through (capped to keep frontmatter tractable).
    tag_set = {t.lower() for t in (tags or [])}
    out_tags = tuple(sorted(tag_set))[:50]

    return Classification(
        kind=modern_kind,
        lifecycle=lifecycle,
        audience=audiences,
        provenance=provenance,
        generator=generator,
        tags=out_tags,
    )
