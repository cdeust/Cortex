"""Three-signal weighted domain classification for cognitive sessions.

Weighted linear combination of three orthogonal signals:
  - Project match (0.5): exact project ID lookup
  - Content match (0.3): Jaccard similarity between keywords
  - Category match (0.2): dot-product of category distributions
"""

from __future__ import annotations

from typing import Any

from mcp_server.shared.categorizer import categorize_with_scores
from mcp_server.shared.project_ids import cwd_to_project_id
from mcp_server.shared.similarity import jaccard_similarity
from mcp_server.shared.text import extract_keywords

W_PROJECT = 0.5
W_CONTENT = 0.3
W_CATEGORY = 0.2

THRESHOLD_CONFIDENT = 0.6
THRESHOLD_TENTATIVE = 0.3


def _score_project_match(project_id: str | None, domain: dict) -> float:
    if not project_id:
        return 0.0
    projects = domain.get("projects") or []
    return 1.0 if project_id in projects else 0.0


def _score_content_match(first_message: str | None, domain: dict) -> float:
    if not first_message:
        return 0.0
    top_keywords = domain.get("topKeywords") or []
    if not top_keywords:
        return 0.0
    msg_keywords = extract_keywords(first_message)
    domain_key_set = {k.lower() for k in top_keywords}
    return jaccard_similarity(msg_keywords, domain_key_set)


def _normalise_category_scores(raw: dict[str, float]) -> dict[str, float]:
    total = sum(raw.values())
    if total == 0:
        return {}
    return {cat: score / total for cat, score in raw.items()}


def _score_category_match(first_message: str | None, domain: dict) -> float:
    if not first_message:
        return 0.0
    cat_dist = domain.get("categoryDistribution") or {}
    if not cat_dist:
        return 0.0
    raw = categorize_with_scores(first_message)
    if not raw:
        return 0.0
    msg_dist = _normalise_category_scores(raw)
    dot = sum(msg_dist.get(cat, 0) * cat_dist.get(cat, 0) for cat in msg_dist)
    return min(1.0, dot)


def map_project_to_domain(project_id: str | None, profiles: dict | None) -> str | None:
    """Look up which domain owns a given project ID."""
    if not project_id or not profiles:
        return None
    domains = profiles.get("domains")
    if not domains:
        return None
    for domain_id, domain in domains.items():
        projects = domain.get("projects") or []
        if project_id in projects:
            return domain_id
    return None


def _rank_domains(
    profiles: dict,
    project_id: str | None,
    first_message: str | None,
) -> list[dict[str, Any]]:
    """Score and rank all domains by weighted signal combination."""
    scored = []
    for domain_id, domain in profiles["domains"].items():
        s_project = _score_project_match(project_id, domain)
        s_content = _score_content_match(first_message, domain)
        s_category = _score_category_match(first_message, domain)

        score = W_PROJECT * s_project + W_CONTENT * s_content + W_CATEGORY * s_category
        scored.append({"id": domain_id, "confidence": score})

    scored.sort(key=lambda d: d["confidence"], reverse=True)
    return scored


def _build_cold_start_result() -> dict[str, Any]:
    """Return the result when no profiles exist yet."""
    return {
        "coldStart": True,
        "domain": None,
        "confidence": 0,
        "isNew": False,
        "alternativeDomains": [],
        "context": "No cognitive profile yet. Building one as we go.",
    }


def _filter_alternatives(
    domain_scores: list[dict[str, Any]],
    min_conf: float,
    max_conf: float | None = None,
) -> list[dict[str, Any]]:
    """Filter runner-up domains within a confidence range."""
    results = []
    for d in domain_scores[1:]:
        if d["confidence"] < min_conf:
            continue
        if max_conf is not None and d["confidence"] >= max_conf:
            continue
        results.append({"id": d["id"], "confidence": d["confidence"]})
    return results


def _build_detection_result(
    domain_scores: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build the detection result from ranked domain scores."""
    best = domain_scores[0]

    if best["confidence"] >= THRESHOLD_CONFIDENT:
        return {
            "coldStart": False,
            "domain": best["id"],
            "confidence": best["confidence"],
            "isNew": False,
            "alternativeDomains": _filter_alternatives(
                domain_scores, THRESHOLD_TENTATIVE, THRESHOLD_CONFIDENT
            ),
        }

    if best["confidence"] >= THRESHOLD_TENTATIVE:
        return {
            "coldStart": False,
            "domain": best["id"],
            "confidence": best["confidence"],
            "isNew": False,
            "alternativeDomains": _filter_alternatives(
                domain_scores, THRESHOLD_TENTATIVE
            ),
        }

    return {
        "coldStart": False,
        "domain": None,
        "confidence": best["confidence"],
        "isNew": True,
        "alternativeDomains": [],
    }


def detect_domain(
    context: dict[str, Any] | None = None,
    profiles: dict | None = None,
) -> dict[str, Any]:
    """Classify which cognitive domain a session belongs to.

    Returns a DetectionResult dict with coldStart, domain, confidence,
    isNew, alternativeDomains, and optional context message.
    """
    context = context or {}
    cwd = context.get("cwd")
    project = context.get("project")
    first_message = context.get("first_message")

    has_domains = profiles and profiles.get("domains") and len(profiles["domains"]) > 0

    if not has_domains:
        return _build_cold_start_result()

    project_id = project or cwd_to_project_id(cwd)
    domain_scores = _rank_domains(profiles, project_id, first_message)

    return _build_detection_result(domain_scores)
