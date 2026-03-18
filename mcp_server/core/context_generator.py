"""Produces human-readable context paragraphs from structured profiles.

Template-based text generation: iterate over profile sections and append
sentences. Deterministic, <200 words for system prompt budget.
"""

from __future__ import annotations

from typing import Any


def _describe_entry_points(profile: dict[str, Any]) -> str | None:
    """Describe the top entry point pattern."""
    entry_points = profile.get("entryPoints") or []
    if not entry_points:
        return None
    return f"You typically {entry_points[0].get('pattern', '')}."


def _describe_recurring_patterns(profile: dict[str, Any]) -> str | None:
    """Describe up to two recurring patterns."""
    recurring = profile.get("recurringPatterns") or []
    if not recurring:
        return None
    patterns = [p.get("pattern", "") for p in recurring[:2]]
    if len(patterns) == 1:
        return f"You {patterns[0]}."
    return f"You {patterns[0]}, and you {patterns[1]}."


def _describe_blind_spots(profile: dict[str, Any]) -> str | None:
    """Describe the top blind spot with optional suggestion."""
    blind_spots = profile.get("blindSpots") or []
    if not blind_spots:
        return None
    top = blind_spots[0]
    text = f"Blind spot: {top.get('description', '')}."
    suggestion = top.get("suggestion")
    if suggestion:
        text += f" {suggestion}."
    return text


def _describe_bridges(profile: dict[str, Any]) -> str | None:
    """Describe the top cross-domain connection."""
    bridges = profile.get("connectionBridges") or []
    if not bridges:
        return None
    top = bridges[0]
    return f"You often connect this to {top.get('toDomain', '')} ({top.get('pattern', '')})."


def _describe_metacognitive(profile: dict[str, Any]) -> str | None:
    """Describe metacognitive style traits."""
    mc = profile.get("metacognitive")
    if not mc:
        return None
    style_parts = []
    if mc.get("explorationStyle"):
        style_parts.append(mc["explorationStyle"])
    if mc.get("problemDecomposition"):
        style_parts.append(mc["problemDecomposition"])
    if not style_parts:
        return None
    return f"You're a {', '.join(style_parts)} thinker."


def _describe_dominant_feature(profile: dict[str, Any]) -> str | None:
    """Describe the dominant behavioral feature activation."""
    activations = profile.get("featureActivations")
    if not activations:
        return None
    max_label = max(activations, key=lambda k: abs(activations[k]))
    return f"Your dominant behavioral mode is {max_label}."


def generate_context(domain: str | None, profile: dict[str, Any] | None) -> str:
    """Generate a full context paragraph from a domain profile."""
    if not profile or not domain:
        return "No cognitive profile yet. Building one as we go."

    parts: list[str] = [f"You're working in {profile.get('label') or domain}."]

    for descriptor in (
        _describe_entry_points,
        _describe_recurring_patterns,
        _describe_blind_spots,
        _describe_bridges,
        _describe_metacognitive,
    ):
        text = descriptor(profile)
        if text:
            parts.append(text)

    session_shape = profile.get("sessionShape")
    if session_shape and session_shape.get("dominantMode"):
        parts.append(f"You prefer {session_shape['dominantMode']} sessions.")

    text = _describe_dominant_feature(profile)
    if text:
        parts.append(text)

    session_count = profile.get("sessionCount", 0) or 0
    confidence = profile.get("confidence", 0) or 0
    parts.append(
        f"Based on {session_count} prior sessions with {round(confidence * 100)}% confidence."
    )

    return " ".join(parts)


def generate_short_context(
    domain: str | None, profile: dict[str, Any] | None
) -> str | None:
    """Generate a compact context label: 'domain . style . mode'."""
    if not profile or not domain:
        return None

    parts: list[str] = []
    parts.append(profile.get("label") or domain)

    mc = profile.get("metacognitive")
    if mc:
        if mc.get("explorationStyle"):
            parts.append(mc["explorationStyle"])
        if mc.get("problemDecomposition"):
            parts.append(mc["problemDecomposition"])

    session_shape = profile.get("sessionShape")
    if session_shape and session_shape.get("dominantMode"):
        parts.append(session_shape["dominantMode"])

    return " · ".join(parts)
