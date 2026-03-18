"""EMA (Exponential Moving Average) update for Felder-Silverman cognitive style.

Blends an existing style profile with a new observation using weighted
averaging for continuous dimensions and majority-rule for categorical ones.

Pure business logic -- no I/O.
"""

from __future__ import annotations

from typing import Any


def _clamp(v: float) -> float:
    """Clamp value to [-1.0, 1.0]."""
    return max(-1.0, min(1.0, v))


def _blend_continuous(
    old_style: dict,
    new_observation: dict,
    alpha: float,
) -> tuple[float, float, float]:
    """Blend continuous dimensions via EMA."""
    ar = _clamp(
        alpha * (new_observation.get("activeReflective") or 0)
        + (1 - alpha) * (old_style.get("activeReflective") or 0)
    )
    si = _clamp(
        alpha * (new_observation.get("sensingIntuitive") or 0)
        + (1 - alpha) * (old_style.get("sensingIntuitive") or 0)
    )
    sg = _clamp(
        alpha * (new_observation.get("sequentialGlobal") or 0)
        + (1 - alpha) * (old_style.get("sequentialGlobal") or 0)
    )
    return ar, si, sg


def _select_categorical(
    old_style: dict,
    new_observation: dict,
    alpha: float,
) -> tuple[str, str, str]:
    """Select categorical dimensions based on alpha threshold."""
    adopt_new = alpha >= 0.5
    primary = new_observation if adopt_new else old_style
    fallback = old_style if adopt_new else new_observation

    pd = primary.get("problemDecomposition") or fallback.get("problemDecomposition")
    es = primary.get("explorationStyle") or fallback.get("explorationStyle")
    vb = primary.get("verificationBehavior") or fallback.get("verificationBehavior")
    return pd, es, vb


def update_style_ema(
    old_style: dict | None,
    new_observation: dict | None,
    alpha: float = 0.1,
) -> dict[str, Any]:
    """Blend an existing style with a new observation using EMA."""
    if not old_style:
        return new_observation
    if not new_observation:
        return old_style

    ar, si, sg = _blend_continuous(old_style, new_observation, alpha)
    pd, es, vb = _select_categorical(old_style, new_observation, alpha)

    return {
        "activeReflective": ar,
        "sensingIntuitive": si,
        "sequentialGlobal": sg,
        "problemDecomposition": pd,
        "explorationStyle": es,
        "verificationBehavior": vb,
    }
