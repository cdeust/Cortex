"""Cross-domain behavioral feature persistence detection.

Detects features active in >50% of domains (persistent).
Ranks by persistence then consistency (low variance).
"""

from __future__ import annotations

import math
from typing import Any


def _populate_from_domain_activations(
    domain_activations: dict,
    feature_activations: dict[str, dict[str, dict]],
) -> None:
    """Fill feature_activations from explicit per-domain activation data."""
    for domain_id, activations in domain_activations.items():
        for activation in activations:
            weights = activation.get("weights") or {}
            items = weights.items() if isinstance(weights, dict) else weights
            for label, weight in items:
                if label not in feature_activations:
                    continue
                domain_map = feature_activations[label]
                existing = domain_map.get(domain_id, {"sum": 0, "count": 0})
                existing["sum"] += abs(weight)
                existing["count"] += 1
                domain_map[domain_id] = existing


def _populate_from_profiles(
    profiles: dict,
    feature_activations: dict[str, dict[str, dict]],
) -> None:
    """Fill feature_activations from profile featureActivations fields."""
    for domain_id, profile in profiles.items():
        fa = profile.get("featureActivations")
        if not fa:
            continue
        for label, weight in fa.items():
            if label not in feature_activations:
                continue
            feature_activations[label][domain_id] = {
                "sum": abs(weight),
                "count": 1,
            }


def _compute_persistence_stats(
    domain_map: dict[str, dict],
    total_domains: int,
    activation_threshold: float,
) -> tuple[float, float, list[str]]:
    """Compute persistence ratio, std deviation, and active domain list."""
    active_domains = []
    activation_values = []

    for domain_id, stats in domain_map.items():
        mean_activation = stats["sum"] / stats["count"] if stats["count"] > 0 else 0
        if mean_activation >= activation_threshold:
            active_domains.append(domain_id)
            activation_values.append(mean_activation)

    persistence = len(active_domains) / total_domains if total_domains else 0

    if not activation_values:
        return persistence, 0.0, active_domains

    mean = sum(activation_values) / len(activation_values)
    variance = sum((v - mean) ** 2 for v in activation_values) / len(activation_values)
    consistency = math.sqrt(variance)

    return persistence, consistency, active_domains


def _build_feature_activations(
    profiles: dict | None,
    dictionary: dict,
    domain_activations: dict | None,
) -> dict[str, dict[str, dict]]:
    """Initialize and populate feature activation maps."""
    feature_activations: dict[str, dict[str, dict]] = {}
    for feature in dictionary["features"]:
        feature_activations[feature["label"]] = {}

    if domain_activations:
        _populate_from_domain_activations(domain_activations, feature_activations)
    else:
        _populate_from_profiles(profiles or {}, feature_activations)

    return feature_activations


def detect_persistent_features(
    profiles: dict | None,
    dictionary: dict | None,
    domain_activations: dict | None = None,
) -> list[dict[str, Any]]:
    if not dictionary or not dictionary.get("features"):
        return []

    domain_ids = list((profiles or {}).keys())
    if len(domain_ids) < 2:
        return []

    feature_activations = _build_feature_activations(
        profiles, dictionary, domain_activations
    )

    activation_threshold = 0.1
    persistence_threshold = 0.5

    results = []
    for label, domain_map in feature_activations.items():
        persistence, consistency, active_domains = _compute_persistence_stats(
            domain_map, len(domain_ids), activation_threshold
        )
        if persistence >= persistence_threshold:
            results.append(
                {
                    "label": label,
                    "persistence": round(persistence * 100) / 100,
                    "consistency": round(consistency * 1000) / 1000,
                    "domains": active_domains,
                }
            )

    results.sort(key=lambda x: (-x["persistence"], x["consistency"]))
    return results


def compare_feature_profiles(
    activations_a: dict | None,
    activations_b: dict | None,
    dictionary: dict | None = None,
) -> dict[str, list[str]]:
    threshold = 0.1
    active_a = {
        label
        for label, weight in (activations_a or {}).items()
        if abs(weight) >= threshold
    }
    active_b = {
        label
        for label, weight in (activations_b or {}).items()
        if abs(weight) >= threshold
    }

    shared = [label for label in active_a if label in active_b]
    unique_to_a = [label for label in active_a if label not in active_b]
    unique_to_b = [label for label in active_b if label not in active_a]

    return {"shared": shared, "uniqueToA": unique_to_a, "uniqueToB": unique_to_b}
