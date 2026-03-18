"""Behavioral feature dictionary learning via greedy sparse coding (OMP).

27-dimensional activation space: tool ratios (7), keyword densities (4),
temporal signals (5), derived (1), category scores (10).
K=15 atoms, sparsity S=3, Cramer's rule least-squares.
"""

from __future__ import annotations

from typing import Any

from mcp_server.shared.linear_algebra import norm, normalize, zeros
from mcp_server.core.sparse_dictionary_activation import (
    SIGNAL_NAMES,
    D,
    extract_session_activation,
)
from mcp_server.core.sparse_dictionary_learning import (
    omp,
    initialize_atoms as _initialize_atoms,
    update_dictionary as _update_dictionary,
)

# ---------------------------------------------------------------------------
# Static seed dictionary for cold start (<10 sessions)
# ---------------------------------------------------------------------------

_SEED_FEATURES = [
    {
        "label": "rapid-fix",
        "description": "Quick bug fixes with minimal exploration",
        "signals": {
            "tool:Edit": 0.6,
            "tmp:burst": 0.5,
            "cat:bug-fix": 0.5,
            "tmp:duration": -0.3,
        },
    },
    {
        "label": "deep-research",
        "description": "Extended reading and analysis sessions",
        "signals": {
            "tool:Read": 0.5,
            "tool:Grep": 0.4,
            "tmp:exploration": 0.5,
            "tmp:turnCount": 0.3,
        },
    },
    {
        "label": "architecture-exploration",
        "description": "Broad structural investigation",
        "signals": {
            "kw:abstract": 0.5,
            "tool:Glob": 0.4,
            "tmp:fileSpread": 0.4,
            "cat:architecture": 0.4,
        },
    },
    {
        "label": "test-driven",
        "description": "Test-first development workflow",
        "signals": {"tool:Bash": 0.5, "cat:testing": 0.6, "kw:planning": 0.3},
    },
    {
        "label": "iterative-refinement",
        "description": "Repeated edit-test cycles",
        "signals": {
            "tool:Edit": 0.4,
            "tool:Bash": 0.3,
            "kw:trial": 0.4,
            "tmp:turnCount": 0.3,
        },
    },
    {
        "label": "documentation-focus",
        "description": "Writing and reviewing docs",
        "signals": {"tool:Write": 0.5, "cat:documentation": 0.6, "kw:concrete": 0.3},
    },
    {
        "label": "devops-automation",
        "description": "Infrastructure and deployment work",
        "signals": {"tool:Bash": 0.5, "cat:devops": 0.6, "tool:Agent": 0.3},
    },
    {
        "label": "code-review",
        "description": "Reading and reviewing existing code",
        "signals": {
            "tool:Read": 0.5,
            "tool:Grep": 0.3,
            "cat:code-review": 0.5,
            "kw:concrete": 0.3,
        },
    },
]


def _build_seed_feature(idx: int, seed: dict) -> dict[str, Any]:
    """Build a single seed feature from its definition."""
    direction = zeros(D)
    for signal, weight in seed["signals"].items():
        si = SIGNAL_NAMES.index(signal) if signal in SIGNAL_NAMES else -1
        if si != -1:
            direction[si] = weight
    normalized = normalize(direction)
    top_signals = sorted(
        [{"signal": s, "weight": w} for s, w in seed["signals"].items()],
        key=lambda x: abs(x["weight"]),
        reverse=True,
    )
    return {
        "index": idx,
        "label": seed["label"],
        "description": seed["description"],
        "direction": normalized,
        "topSignals": top_signals,
    }


def build_seed_dictionary() -> dict[str, Any]:
    """Build the cold-start seed dictionary from static feature definitions."""
    features = [
        _build_seed_feature(idx, seed) for idx, seed in enumerate(_SEED_FEATURES)
    ]
    return {
        "K": len(features),
        "D": D,
        "sparsity": 3,
        "signalNames": list(SIGNAL_NAMES),
        "features": features,
        "learnedFromSessions": 0,
    }


# ---------------------------------------------------------------------------
# Dictionary learning
# ---------------------------------------------------------------------------


def learn_dictionary(
    conversations: list[dict] | None,
    options: dict | None = None,
) -> dict[str, Any]:
    """Learn a feature dictionary from conversation data via K-SVD.

    Falls back to the seed dictionary if fewer than 10 conversations.
    """
    options = options or {}
    K = options.get("K", 15)
    sparsity = options.get("sparsity", 3)
    iterations = options.get("iterations", 5)

    if not conversations or len(conversations) < 10:
        return build_seed_dictionary()

    data = [extract_session_activation(c) for c in conversations]
    atoms = _initialize_atoms(data, K)
    atoms = _update_dictionary(data, atoms, sparsity, iterations, D)

    features = [label_feature(direction, idx) for idx, direction in enumerate(atoms)]

    return {
        "K": len(atoms),
        "D": D,
        "sparsity": sparsity,
        "signalNames": list(SIGNAL_NAMES),
        "features": features,
        "learnedFromSessions": len(conversations),
    }


# ---------------------------------------------------------------------------
# Feature labeling
# ---------------------------------------------------------------------------

_SIGNAL_LABELS = {
    "tool:Read": "reading",
    "tool:Edit": "editing",
    "tool:Write": "writing",
    "tool:Grep": "searching",
    "tool:Glob": "scanning",
    "tool:Bash": "executing",
    "tool:Agent": "delegating",
    "kw:abstract": "abstract-thinking",
    "kw:concrete": "concrete-thinking",
    "kw:planning": "planning",
    "kw:trial": "experimenting",
    "tmp:duration": "long-session",
    "tmp:turnCount": "high-interaction",
    "tmp:burst": "burst-mode",
    "tmp:exploration": "exploration-mode",
    "tmp:fileSpread": "wide-exploration",
    "drv:editReadRatio": "edit-heavy",
    "cat:bug-fix": "bug-fixing",
    "cat:feature": "feature-building",
    "cat:refactoring": "refactoring",
    "cat:testing": "testing",
    "cat:documentation": "documenting",
    "cat:devops": "devops",
    "cat:code-review": "reviewing",
    "cat:debugging": "debugging",
    "cat:architecture": "architecting",
    "cat:general": "general-work",
}


def label_feature(direction: list[float], index: int) -> dict[str, Any]:
    """Generate a human-readable label and description for a feature atom."""
    weighted = [
        {"signal": SIGNAL_NAMES[i], "weight": direction[i]}
        for i in range(len(SIGNAL_NAMES))
        if i < len(direction) and abs(direction[i]) > 0.05
    ]
    weighted.sort(key=lambda x: abs(x["weight"]), reverse=True)
    top_signals = weighted[:5]
    top_signal = top_signals[0] if top_signals else None

    label = f"feature-{index}"
    description = "Behavioral feature"

    if top_signal:
        label = _SIGNAL_LABELS.get(top_signal["signal"], f"feature-{index}")
        secondary = top_signals[1] if len(top_signals) > 1 else None
        if secondary:
            second_label = _SIGNAL_LABELS.get(secondary["signal"], "")
            description = f"{label} with {second_label} tendency"
        else:
            description = f"Dominant {label} behavioral mode"

    return {
        "index": index,
        "label": label,
        "description": description,
        "direction": direction,
        "topSignals": top_signals,
    }


def encode_session(conversation: dict, dictionary: dict) -> dict[str, Any]:
    """Encode a single conversation against a learned dictionary."""
    activation = extract_session_activation(conversation)
    atoms = [f["direction"] for f in dictionary["features"]]
    result = omp(activation, atoms, dictionary["sparsity"])

    weights: dict[str, float] = {}
    for i, idx in enumerate(result["indices"]):
        feature = dictionary["features"][idx]
        if feature and abs(result["coefficients"][i]) > 1e-10:
            weights[feature["label"]] = result["coefficients"][i]

    return {
        "weights": weights,
        "reconstructionError": norm(result["residual"]),
    }
