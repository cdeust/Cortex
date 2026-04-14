"""Phase 2.4 — Draft curation.

Pure-logic gate: given a DraftPage and its KindDefinition, decide
whether to approve, reject, or hold for review.

Hard-rule gate (no LLM): a draft must satisfy all of:
  - confidence ≥ MIN_CONFIDENCE
  - all required sections present and non-placeholder
  - lead present, non-placeholder, ≤ MAX_LEAD_WORDS
  - title is a noun phrase (not imperative-shaped)

Drafts that PASS → approved.
Drafts that FAIL → return 'reject' with reasons (curator handler may
                  log the rejection but keep the draft for refinement).
Drafts that are CLOSE → 'hold' (recoverable via Path B refinement).

Pure logic, no I/O. The handler persists the decision via
update_draft_status + insert_memo.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from mcp_server.core.wiki_schema_loader import KindDefinition

CurationVerdict = Literal["approved", "rejected", "hold"]

MIN_CONFIDENCE_APPROVE = 0.6
MIN_CONFIDENCE_HOLD = 0.4
MAX_LEAD_WORDS = 80
PLACEHOLDER_PREFIX = "_(to be filled)_"
PLACEHOLDER_LEAD_MARKERS = ("_(no claims yet", "_(to be filled)_")

# Imperative title shapes from the wiki classifier — duplicated here so
# the curator stays self-contained and doesn't depend on the noise gate.
_IMPERATIVE_TITLE_RE = re.compile(
    r"^\s*(let'?s|use|fetch|take|give|look at|verify|audit|check|make|do|"
    r"run|push|remove|rename|adapt|implement|execute|perform|replace|"
    r"add|delete|update|modify|fix|install|setup|configure|create|build|"
    r"write|test|sync|import|move|copy|ensure|try|go|start|stop|open|"
    r"close|clean|restart|refactor|migrate|enable|disable|apply|reset|"
    r"rebuild|regenerate|analyze)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class CurationDecision:
    """Outcome of evaluating one draft."""

    verdict: CurationVerdict
    reasons: tuple[str, ...]
    score: float  # 0.0–1.0 — how close to approval the draft is


def _word_count(text: str) -> int:
    return len((text or "").split())


def _section_is_filled(body: str) -> bool:
    """A section is filled when it has prose beyond the placeholder."""
    if not body or not body.strip():
        return False
    if body.strip().startswith(PLACEHOLDER_PREFIX):
        return False
    return True


def _missing_required_sections(sections: list, required: list[str]) -> list[str]:
    """Return the subset of required sections that are missing or empty."""
    by_heading: dict[str, str] = {}
    for s in sections:
        # accept either Pydantic Section or dict
        heading = getattr(s, "heading", None) or s.get("heading", "")
        body = getattr(s, "body", None) or s.get("body", "")
        by_heading[heading.strip()] = body
    missing: list[str] = []
    for h in required:
        body = by_heading.get(h)
        if body is None or not _section_is_filled(body):
            missing.append(h)
    return missing


def _title_is_imperative(title: str) -> bool:
    return bool(_IMPERATIVE_TITLE_RE.match(title or ""))


def _lead_is_placeholder(lead: str) -> bool:
    if not lead:
        return True
    return lead.strip().startswith(PLACEHOLDER_LEAD_MARKERS)


def evaluate_draft(
    draft: dict,
    kind_definition: KindDefinition | None,
) -> CurationDecision:
    """Evaluate a single draft. Returns approval verdict + reasons."""
    reasons: list[str] = []
    score = 1.0  # start full and subtract

    confidence = float(draft.get("confidence", 0.0))
    title = draft.get("title", "") or ""
    lead = draft.get("lead", "") or ""
    sections = draft.get("sections") or []
    required = list(kind_definition.required_sections) if kind_definition else []

    # 1. Confidence floor
    if confidence < MIN_CONFIDENCE_HOLD:
        reasons.append(
            f"confidence {confidence:.2f} below hold threshold {MIN_CONFIDENCE_HOLD}"
        )
        score -= 0.4
    elif confidence < MIN_CONFIDENCE_APPROVE:
        reasons.append(
            f"confidence {confidence:.2f} below approve threshold "
            f"{MIN_CONFIDENCE_APPROVE}"
        )
        score -= 0.15

    # 2. Title shape — must not be imperative
    if _title_is_imperative(title):
        reasons.append(f"title is imperative-shaped: {title!r}")
        score -= 0.25
    elif not title.strip():
        reasons.append("title is empty")
        score -= 0.3

    # 3. Lead non-placeholder, length cap
    if _lead_is_placeholder(lead):
        reasons.append("lead is placeholder")
        score -= 0.25
    else:
        wc = _word_count(lead)
        if wc > MAX_LEAD_WORDS:
            reasons.append(f"lead too long ({wc} words > {MAX_LEAD_WORDS})")
            score -= 0.1

    # 4. Required sections filled
    missing = _missing_required_sections(sections, required)
    if missing:
        reasons.append(f"missing required sections: {missing}")
        score -= 0.15 * len(missing)

    score = max(0.0, score)

    if not reasons:
        return CurationDecision(verdict="approved", reasons=(), score=score)
    if confidence < MIN_CONFIDENCE_HOLD or score < 0.3:
        return CurationDecision(verdict="rejected", reasons=tuple(reasons), score=score)
    return CurationDecision(verdict="hold", reasons=tuple(reasons), score=score)
