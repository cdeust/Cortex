"""Assemble domain profiles from scan data.

Orchestrates pattern extraction, style classification, bridge finding,
blind spot detection, dictionary learning, persona vectors, and crosscoding.
"""

from __future__ import annotations

from typing import Any

from mcp_server.core.pattern_extractor import extract_patterns
from mcp_server.core.style_classifier import classify_style
from mcp_server.core.bridge_finder import find_bridges
from mcp_server.core.blindspot_detector import detect_blind_spots
from mcp_server.core.sparse_dictionary import learn_dictionary, encode_session
from mcp_server.core.persona_vector import build_persona_vector
from mcp_server.core.behavioral_crosscoder import detect_persistent_features
from mcp_server.shared.project_ids import project_id_to_label, domain_id_from_label
from mcp_server.shared.categorizer import categorize_with_scores


def _build_project_domain_map(
    profiles: dict,
    by_project: dict[str, list[dict]],
) -> dict[str, str]:
    """Map each project ID to its domain ID."""
    project_domains: dict[str, str] = {}
    for domain_id, domain in (profiles.get("domains") or {}).items():
        for proj in domain.get("projects") or []:
            project_domains[proj] = domain_id

    for proj in by_project:
        if proj not in project_domains:
            label = project_id_to_label(proj)
            project_domains[proj] = domain_id_from_label(label)

    return project_domains


def _group_conversations_by_domain(
    by_project: dict[str, list[dict]],
    project_domains: dict[str, str],
    target_domain: str | None,
) -> dict[str, dict]:
    """Group conversations by domain, optionally filtering to target_domain."""
    domain_conversations: dict[str, dict] = {}
    for proj, convs in by_project.items():
        domain_id = project_domains.get(proj)
        if not domain_id:
            continue
        if target_domain and domain_id != target_domain:
            continue
        if domain_id not in domain_conversations:
            domain_conversations[domain_id] = {"conversations": [], "projects": set()}
        domain_conversations[domain_id]["conversations"].extend(convs)
        domain_conversations[domain_id]["projects"].add(proj)
    return domain_conversations


def _compute_category_distribution(convs: list[dict]) -> dict[str, float]:
    """Compute multi-category distribution across conversations."""
    categories: dict[str, float] = {}
    total = 0
    for conv in convs:
        text = conv.get("allText") or conv.get("firstMessage") or ""
        if not text:
            continue
        scores = categorize_with_scores(text)
        for cat in scores:
            categories[cat] = categories.get(cat, 0) + 1
        if not scores:
            categories["general"] = categories.get("general", 0) + 1
        total += 1

    if total > 0:
        for cat in categories:
            categories[cat] = round((categories[cat] / total) * 100) / 100

    return categories


def _extract_top_keywords(convs: list[dict], limit: int = 20) -> list[str]:
    """Extract the most frequent keywords across conversations."""
    freq: dict[str, int] = {}
    for conv in convs:
        kws = conv.get("keywords")
        if not kws:
            continue
        for kw in kws if isinstance(kws, (list, set)) else []:
            freq[kw] = freq.get(kw, 0) + 1
    return [
        kw for kw, _ in sorted(freq.items(), key=lambda x: x[1], reverse=True)[:limit]
    ]


def _compute_timestamps(convs: list[dict]) -> tuple[str | None, str | None]:
    """Extract first_seen and last_updated from sorted timestamps."""
    timestamps = sorted(
        t for c in convs for t in [c.get("startedAt") or c.get("endedAt")] if t
    )
    first_seen = timestamps[0] if timestamps else None
    last_updated = timestamps[-1] if timestamps else None
    return first_seen, last_updated


def _build_single_domain(
    domain_id: str,
    data: dict,
) -> dict[str, Any]:
    """Build a single domain profile dict from its conversations."""
    convs = data["conversations"]
    patterns = extract_patterns(convs)
    metacognitive = classify_style(convs)
    categories = _compute_category_distribution(convs)
    top_keywords = _extract_top_keywords(convs)
    first_seen, last_updated = _compute_timestamps(convs)

    data_quality = min(len(convs) / 10, 1.0)
    confidence = round(min(len(convs) / 50, 1.0) * data_quality * 100) / 100
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
        "K": fd["K"],
        "D": fd["D"],
        "sparsity": fd["sparsity"],
        "signalNames": fd["signalNames"],
        "features": [
            {
                "index": f["index"],
                "label": f["label"],
                "description": f["description"],
                "topSignals": f["topSignals"],
            }
            for f in fd["features"]
        ],
        "learnedFromSessions": fd["learnedFromSessions"],
        "_raw": fd,
    }


def _encode_domain_activations(
    domain_conversations: dict[str, dict],
    profiles: dict,
    feature_dictionary: dict,
) -> dict[str, list]:
    """Encode sessions per domain and attach feature activations + persona vectors."""
    raw_fd = feature_dictionary["_raw"]
    domain_activations: dict[str, list] = {}

    for domain_id, data in domain_conversations.items():
        if domain_id not in profiles["domains"]:
            continue
        encodings = [encode_session(c, raw_fd) for c in data["conversations"]]
        domain_activations[domain_id] = encodings

        mean_activations: dict[str, float] = {}
        for enc in encodings:
            weights = enc["weights"]
            items = weights.items() if isinstance(weights, dict) else weights
            for label, weight in items:
                mean_activations[label] = mean_activations.get(label, 0) + weight / len(
                    encodings
                )

        profiles["domains"][domain_id]["featureActivations"] = mean_activations
        profiles["domains"][domain_id]["personaVector"] = build_persona_vector(
            profiles["domains"][domain_id]
        )

    return domain_activations


def _compute_global_style(profiles: dict) -> None:
    """Compute session-weighted global cognitive style across all domains."""
    all_domains = list(profiles.get("domains", {}).values())
    if not all_domains:
        return

    total_sessions = 0
    ar_sum = si_sum = sg_sum = 0.0
    for d in all_domains:
        sc = d.get("sessionCount") or 0
        total_sessions += sc
        mc = d.get("metacognitive") or {}
        ar_sum += (mc.get("activeReflective") or 0) * sc
        si_sum += (mc.get("sensingIntuitive") or 0) * sc
        sg_sum += (mc.get("sequentialGlobal") or 0) * sc

    if total_sessions > 0:
        profiles["globalStyle"] = {
            "activeReflective": round((ar_sum / total_sessions) * 100) / 100,
            "sensingIntuitive": round((si_sum / total_sessions) * 100) / 100,
            "sequentialGlobal": round((sg_sum / total_sessions) * 100) / 100,
            "confidence": round(min(total_sessions / 100, 1.0) * 100) / 100,
            "sessionCount": total_sessions,
        }


def _apply_cross_domain_analysis(
    profiles: dict,
    domain_conversations: dict[str, dict],
    conversations: list[dict],
    brain_index: dict | None,
    memories: dict | None,
) -> None:
    """Attach bridges, blind spots, features, and persistent features."""
    bridges = find_bridges(profiles, brain_index, memories)
    for domain_id, domain_bridges in bridges.items():
        if domain_id in profiles["domains"]:
            profiles["domains"][domain_id]["connectionBridges"] = domain_bridges

    for domain_id, data in domain_conversations.items():
        if domain_id not in profiles["domains"]:
            continue
        blind_spots = detect_blind_spots(
            domain_id,
            data["conversations"],
            conversations,
            profiles,
        )
        profiles["domains"][domain_id]["blindSpots"] = blind_spots

    fd = _build_feature_dictionary(domain_conversations)
    profiles["featureDictionary"] = {k: v for k, v in fd.items() if k != "_raw"}

    domain_activations = _encode_domain_activations(
        domain_conversations,
        profiles,
        fd,
    )
    profiles["persistentFeatures"] = detect_persistent_features(
        profiles.get("domains"),
        fd["_raw"],
        domain_activations,
    )


def build_domain_profiles(
    *,
    existing_profiles: dict,
    conversations: list[dict],
    memories: dict | None,
    brain_index: dict | None,
    by_project: dict[str, list[dict]],
    target_domain: str | None = None,
) -> dict:
    """Build or update domain profiles from scanned conversation data."""
    profiles = existing_profiles
    project_domains = _build_project_domain_map(profiles, by_project)
    domain_conversations = _group_conversations_by_domain(
        by_project,
        project_domains,
        target_domain,
    )

    if "domains" not in profiles:
        profiles["domains"] = {}

    for domain_id, data in domain_conversations.items():
        if not data["conversations"]:
            continue
        profiles["domains"][domain_id] = _build_single_domain(domain_id, data)

    _apply_cross_domain_analysis(
        profiles,
        domain_conversations,
        conversations,
        brain_index,
        memories,
    )
    _compute_global_style(profiles)

    return profiles
