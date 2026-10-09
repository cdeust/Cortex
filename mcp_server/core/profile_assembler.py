"""Assemble domain profiles from scan data.

Orchestrates pattern extraction, style classification, bridge finding,
blind spot detection, dictionary learning, persona vectors, and crosscoding.
"""

from __future__ import annotations

from typing import Any

from mcp_server.core.behavioral_crosscoder import detect_persistent_features
from mcp_server.core.blindspot_detector import detect_blind_spots
from mcp_server.core.bridge_finder import find_bridges
from mcp_server.core.pattern_extractor import extract_patterns
from mcp_server.core.persona_vector import build_persona_vector
from mcp_server.core.profile_domain_stats import (
    compute_category_distribution,
    compute_global_style,
    compute_timestamps,
    extract_top_keywords,
)
from mcp_server.core.profile_domain_grouping import (
    build_project_domain_map,
    group_conversations_by_domain,
)
from mcp_server.core.profile_rebuild_policy import (
    DomainOutcome,
    ProfileBuild,
    decide_domain_outcome,
)
from mcp_server.core.sparse_dictionary import encode_session, learn_dictionary
from mcp_server.core.style_classifier import classify_style
from mcp_server.shared.project_ids import project_id_to_label


def _build_single_domain(
    domain_id: str,
    data: dict,
) -> dict[str, Any]:
    """Build a single domain profile dict from its conversations."""
    convs = data["conversations"]
    patterns = extract_patterns(convs)
    metacognitive = classify_style(convs)
    categories = compute_category_distribution(convs)
    top_keywords = extract_top_keywords(convs)
    first_seen, last_updated = compute_timestamps(convs)

    data_quality = min(len(convs) / 10, 1.0)
    confidence = round(min(len(convs) / 50, 1.0) * data_quality * 100) / 100
    # source: ADR-0227

    if domain_id and "-" in domain_id and not domain_id.startswith("-"):
        label = domain_id.replace("-", " ").title()
    else:
        label = project_id_to_label(next(iter(data["projects"])))

    return {
        "id": domain_id,
        "label": label,
        "projects": list(data["projects"]),
        "categories": categories,
        "topKeywords": top_keywords,
        "entryPoints": patterns["entryPoints"],
        "recurringPatterns": patterns["recurringPatterns"],
        "toolPreferences": patterns["toolPreferences"],
        "sessionShape": patterns["sessionShape"],
        "connectionBridges": [],
        "blindSpots": [],
        "metacognitive": metacognitive,
        "confidence": confidence,
        "sessionCount": len(convs),
        "lastUpdated": last_updated,
        "firstSeen": first_seen,
    }


def _build_feature_dictionary(
    domain_conversations: dict[str, dict],
) -> dict:
    """Learn sparse feature dictionary from all conversations."""
    all_convs = [c for d in domain_conversations.values() for c in d["conversations"]]
    fd = learn_dictionary(all_convs)
    return {
        "K": fd.K,
        "D": fd.D,
        "sparsity": fd.sparsity,
        "signalNames": fd.signal_names,
        "features": [
            {
                "index": f.index,
                "label": f.label,
                "description": f.description,
                "topSignals": [ts.model_dump() for ts in f.top_signals],
            }
            for f in fd.features
        ],
        "learnedFromSessions": fd.learned_from_sessions,
        "_raw": fd,
    }


def _encode_domain_activations(
    domain_conversations: dict[str, dict],
    profiles: dict,
    feature_dictionary: dict,
    kept: set[str],
) -> dict[str, list]:
    """Encode every scanned domain's sessions; attach feature activations and
    persona vectors to every domain except the ``kept`` ones, which keep their
    stored values (their encodings still feed the persistence statistics).
    """
    raw_fd = feature_dictionary["_raw"]
    domain_activations: dict[str, list] = {}

    for domain_id, data in domain_conversations.items():
        if domain_id not in profiles["domains"]:
            continue
        encodings = [encode_session(c, raw_fd) for c in data["conversations"]]
        domain_activations[domain_id] = encodings
        if domain_id in kept:
            continue

        mean_activations: dict[str, float] = {}
        for enc in encodings:
            for label, weight in enc.weights.items():
                mean_activations[label] = mean_activations.get(label, 0) + weight / len(
                    encodings
                )

        profiles["domains"][domain_id]["featureActivations"] = mean_activations
        profiles["domains"][domain_id]["personaVector"] = build_persona_vector(
            profiles["domains"][domain_id]
        )

    return domain_activations


def _attach_bridges_and_blind_spots(
    profiles: dict,
    domain_conversations: dict[str, dict],
    conversations: list[dict],
    brain_index: dict | None,
    memories: dict | list[dict] | None,
    kept: set[str],
) -> None:
    """Write bridges and blind spots to every domain that is not ``kept``."""
    bridges = find_bridges(profiles, brain_index, memories)
    for domain_id, domain_bridges in bridges.items():
        if domain_id in profiles["domains"] and domain_id not in kept:
            profiles["domains"][domain_id]["connectionBridges"] = domain_bridges

    for domain_id, data in domain_conversations.items():
        if domain_id in kept or domain_id not in profiles["domains"]:
            continue
        blind_spots = detect_blind_spots(
            domain_id,
            data["conversations"],
            conversations,
            profiles,
        )
        profiles["domains"][domain_id]["blindSpots"] = blind_spots


def _apply_cross_domain_analysis(
    profiles: dict,
    domain_conversations: dict[str, dict],
    conversations: list[dict],
    brain_index: dict | None,
    memories: dict | list[dict] | None,
    kept: set[str],
) -> None:
    """Attach bridges, blind spots, features, and persistent features.

    A ``kept`` domain's stored profile is not written to: its bridges, blind
    spots, feature activations and persona vector are not recomputed from a
    scan that saw fewer sessions than the profile records. Its scanned
    sessions still feed the shared dictionary and the persistence statistics.
    """
    _attach_bridges_and_blind_spots(
        profiles, domain_conversations, conversations, brain_index, memories, kept
    )

    fd = _build_feature_dictionary(domain_conversations)
    profiles["featureDictionary"] = {k: v for k, v in fd.items() if k != "_raw"}

    domain_activations = _encode_domain_activations(
        domain_conversations,
        profiles,
        fd,
        kept,
    )
    persistent_features = detect_persistent_features(
        profiles.get("domains"),
        fd["_raw"],
        domain_activations,
    )
    # profiles is JSON-persisted (profiles.json) — project the typed models
    # back to plain dicts at this exact disk boundary.
    profiles["persistentFeatures"] = [pf.model_dump() for pf in persistent_features]


def _rebuild_or_keep(
    profiles: dict,
    domain_conversations: dict[str, dict],
    replace_accumulated: bool,
) -> list[DomainOutcome]:
    """Build each scanned domain's profile unless its stored one is kept."""
    outcomes: list[DomainOutcome] = []
    for domain_id, data in domain_conversations.items():
        if not data["conversations"]:
            continue
        outcome = decide_domain_outcome(
            domain_id,
            profiles["domains"].get(domain_id),
            len(data["conversations"]),
            replace_accumulated,
        )
        outcomes.append(outcome)
        if outcome.action != "kept":
            profiles["domains"][domain_id] = _build_single_domain(domain_id, data)
    return outcomes


def build_domain_profiles(
    *,
    existing_profiles: dict,
    conversations: list[dict],
    memories: dict | list[dict] | None,
    brain_index: dict | None,
    by_project: dict[str, list[dict]],
    target_domain: str | None = None,
    replace_accumulated: bool = False,
) -> ProfileBuild:
    """Build or update domain profiles from scanned conversation data.

    Post: each scanned domain is built from the scan unless ``kept`` (see
    ``decide_domain_outcome``), which leaves its stored profile unchanged;
    unscanned domains are untouched; one outcome per scanned domain.
    """
    profiles = existing_profiles
    project_domains = build_project_domain_map(profiles, by_project)
    domain_conversations = group_conversations_by_domain(
        by_project,
        project_domains,
        target_domain,
    )

    if "domains" not in profiles:
        profiles["domains"] = {}

    outcomes = _rebuild_or_keep(profiles, domain_conversations, replace_accumulated)
    kept = {o.domain for o in outcomes if o.action == "kept"}
    _apply_cross_domain_analysis(
        profiles,
        domain_conversations,
        conversations,
        brain_index,
        memories,
        kept,
    )
    compute_global_style(profiles)

    return ProfileBuild(profiles=profiles, outcomes=outcomes)
