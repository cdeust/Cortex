"""Phase 2.3 (Path A) — Template-driven draft page synthesizer.

Takes a set of resolved ClaimEvents + a target kind, produces a
DraftPage with kind-specific structure. Deterministic, no LLM call.

Routing per kind: each claim_type maps to a target section.
The lead is synthesised from the highest-confidence claim.

Output goes to wiki.drafts with status='pending' for the curate
phase to act on. Phase 2.5 path B replaces these with LLM-refined
drafts via wiki_refine.

Pure logic, no I/O. The handler wires this against pg_store_wiki and
the wiki_schema_loader's KindDefinition registry.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from mcp_server.core.wiki_schema_loader import KindDefinition
from mcp_server.shared.wiki_ir import DraftPage, Provenance, Section


# ── Per-kind claim_type → section routing ─────────────────────────────
#
# Hardcoded defaults. A future Phase 5 step migrates these into the
# KindDefinition frontmatter (e.g. `section_map: {Decision: [decision]}`)
# so users can customise routing without editing Python.

_DEFAULT_ROUTING: dict[str, dict[str, list[str]]] = {
    "adr": {
        "Context": ["observation", "method", "limitation"],
        "Decision": ["decision"],
        "Consequences": ["result", "limitation"],
        "Alternatives Considered": ["question"],
        "References": ["reference"],
    },
    "spec": {
        "Scope": ["decision", "observation"],
        "Inputs": ["method"],
        "Outputs": ["method", "result"],
        "Invariants": ["decision", "method"],
        "Non-Goals": ["limitation"],
        "Error Modes": ["limitation"],
        "References": ["reference"],
    },
    "lesson": {
        "Trigger": ["observation", "limitation"],
        "Root Cause": ["limitation", "observation"],
        "Rule": ["decision", "method"],
        "Evidence": ["result", "reference"],
        "Detection": ["observation", "method"],
    },
    "convention": {
        "Rule": ["decision", "method"],
        "Rationale": ["observation", "decision"],
        "Example": ["method", "result"],
        "Counter-Example": ["limitation"],
        "References": ["reference"],
    },
    "note": {
        "Context": ["observation", "method"],
        "Observations": ["observation", "result", "method"],
        "Open Questions": ["question", "limitation"],
    },
}

# Score weight per claim type when picking the lead claim.
_LEAD_TYPE_BIAS: dict[str, dict[str, float]] = {
    "adr": {"decision": 1.5, "method": 1.0, "observation": 0.8},
    "spec": {"decision": 1.3, "method": 1.4, "result": 1.0},
    "lesson": {"limitation": 1.5, "observation": 1.2, "decision": 1.0},
    "convention": {"decision": 1.5, "method": 1.0},
    "note": {"observation": 1.2, "method": 1.0, "decision": 1.0},
}


@dataclass(frozen=True)
class SynthesisStats:
    """Diagnostics returned alongside the draft."""

    claims_total: int
    claims_routed: int
    sections_filled: int
    sections_required: int


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _lead_score(claim: dict, kind: str) -> float:
    """Score a claim's fitness to become the lead paragraph."""
    base = float(claim.get("confidence", 0.5))
    bias = _LEAD_TYPE_BIAS.get(kind, {}).get(claim.get("claim_type", ""), 0.7)
    has_evidence = bool(claim.get("evidence_refs"))
    evidence_bonus = 0.15 if has_evidence else 0.0
    length = len(claim.get("text", ""))
    # Mid-length claims (50-300 chars) make better leads than fragments
    # or essay-length blobs.
    if 50 <= length <= 300:
        length_bonus = 0.1
    elif length < 50:
        length_bonus = -0.2
    elif length > 600:
        length_bonus = -0.1
    else:
        length_bonus = 0.0
    return base * bias + evidence_bonus + length_bonus


def _truncate_lead(text: str, max_chars: int = 280) -> str:
    """Truncate at a sentence boundary if possible."""
    text = text.strip()
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars]
    # Prefer ending on a full sentence
    for terminator in (". ", "! ", "? "):
        last = cut.rfind(terminator)
        if last > max_chars * 0.6:
            return cut[: last + 1].strip()
    # Fallback: word boundary
    last_space = cut.rfind(" ")
    if last_space > max_chars * 0.7:
        return cut[:last_space].strip() + "…"
    return cut.strip() + "…"


def _route_claims_to_sections(
    claims: list[dict],
    kind: str,
    required_sections: list[str],
    optional_sections: list[str],
) -> tuple[list[Section], int]:
    """Distribute claims into kind-specific sections.

    Returns (sections, claims_routed). Required sections always appear
    even if empty (they're contracts). Optional sections appear only
    when filled.
    """
    routing = _DEFAULT_ROUTING.get(kind, _DEFAULT_ROUTING["note"])
    by_section: dict[str, list[dict]] = {h: [] for h in required_sections}
    for h in optional_sections:
        by_section.setdefault(h, [])

    seen_claim_ids: set[int] = set()
    for c in claims:
        ct = c.get("claim_type", "")
        for heading, accepted_types in routing.items():
            if ct in accepted_types and heading in by_section:
                by_section[heading].append(c)
                seen_claim_ids.add(c.get("id", id(c)))
                break  # one section per claim — no duplication

    # Build Section list, preserving the required order then optional
    sections: list[Section] = []
    for heading in required_sections:
        cs = by_section.get(heading, [])
        sections.append(
            Section(
                heading=heading,
                body=_format_claims_as_prose(cs),
                claim_ids=[c["id"] for c in cs if "id" in c],
            )
        )
    for heading in optional_sections:
        cs = by_section.get(heading, [])
        if not cs:
            continue
        sections.append(
            Section(
                heading=heading,
                body=_format_claims_as_prose(cs),
                claim_ids=[c["id"] for c in cs if "id" in c],
            )
        )

    return sections, len(seen_claim_ids)


def _format_claims_as_prose(claims: list[dict]) -> str:
    """Render a list of claims as a section body.

    Single claim → its text on its own line.
    Multiple claims → bullet list of texts.
    Empty → a placeholder marker the curate phase can detect.
    """
    if not claims:
        return "_(to be filled)_"
    if len(claims) == 1:
        return claims[0].get("text", "").strip()
    return "\n".join(f"- {c.get('text', '').strip()}" for c in claims)


def _derive_title(claims: list[dict], kind: str, lead_claim: dict | None) -> str:
    """Derive a noun-phrase title from the claim corpus.

    Strategy:
      1. Use the lead claim's first sentence trimmed
      2. Strip imperative prefixes
      3. Cap at 80 chars on word boundary
    """
    source = (lead_claim or {}).get("text") or (claims[0]["text"] if claims else "")
    source = source.strip()
    # Take up to first sentence terminator
    for term in (". ", "! ", "? ", "\n"):
        i = source.find(term)
        if 0 < i < 120:
            source = source[:i].strip()
            break
    # Strip common imperative / first-person prefixes
    for prefix in ("We ", "I ", "Let's ", "Decision: ", "Decided: "):
        if source.lower().startswith(prefix.lower()):
            source = source[len(prefix) :].strip()
    if len(source) > 80:
        source = source[:77].rsplit(" ", 1)[0] + "…"
    return source or f"Untitled {kind}"


def synthesize_draft(
    claims: list[dict],
    *,
    kind: str,
    kind_definition: KindDefinition | None = None,
    memory_id: int | None = None,
    concept_id: int | None = None,
) -> tuple[DraftPage, SynthesisStats]:
    """Produce a DraftPage from a set of claims for the given kind.

    Inputs:
      - claims: list of claim dicts (id, text, claim_type, confidence,
                evidence_refs, ...). May be empty (returns an empty draft).
      - kind: target kind name (must be one of the loaded registry kinds
              or one of the hardcoded defaults).
      - kind_definition: optional, supplies required/optional section lists.
                         If omitted, falls back to default per-kind.
      - memory_id / concept_id: at least one identifies the synthesis
                                source for provenance.

    Returns (DraftPage, stats). Never raises on empty input.
    """
    # Resolve required/optional sections
    if kind_definition is not None:
        required = list(kind_definition.required_sections)
        optional = list(kind_definition.optional_sections)
    else:
        required = list(_DEFAULT_ROUTING.get(kind, {}).keys())[:3]
        optional = []

    # Pick the lead claim
    lead_claim: dict | None = None
    if claims:
        lead_claim = max(claims, key=lambda c: _lead_score(c, kind))

    # Build sections from routing
    sections, routed_count = _route_claims_to_sections(claims, kind, required, optional)

    # Build lead paragraph
    if lead_claim:
        lead = _truncate_lead(lead_claim.get("text", ""))
    else:
        lead = "_(no claims yet — empty draft)_"

    # Title
    title = _derive_title(claims, kind, lead_claim)

    # Compute average confidence as the draft's confidence
    confidences = [
        float(c.get("confidence", 0.5))
        for c in claims
        if c.get("confidence") is not None
    ]
    draft_confidence = sum(confidences) / len(confidences) if confidences else 0.4

    # Provenance
    provenance = Provenance(
        source_type="concept"
        if concept_id
        else ("memory" if memory_id else "claim-set"),
        source_ids=[concept_id] if concept_id else ([memory_id] if memory_id else []),
        synthesis_model="template_v1",
        synthesis_prompt_hash=None,
        generated_at=datetime.now(tz=timezone.utc),
    )

    draft = DraftPage(
        memory_id=memory_id,
        concept_id=concept_id,
        title=title,
        kind=kind,
        lead=lead,
        sections=sections,
        frontmatter={"updated": _now_iso()},
        provenance=provenance,
        confidence=draft_confidence,
        status="pending",
    )

    stats = SynthesisStats(
        claims_total=len(claims),
        claims_routed=routed_count,
        sections_filled=sum(
            1 for s in sections if s.body and not s.body.startswith("_(")
        ),
        sections_required=len(required),
    )
    return draft, stats
