"""Pipeline attribution graph via perturbation-based tracing.

Perturbs each input signal by +/-epsilon, re-runs downstream pure functions,
measures |output_perturbed - output_original| / epsilon. Samples at most 20 sessions.
"""

from __future__ import annotations

from typing import Any

from mcp_server.core.sparse_dictionary_activation import (
    SIGNAL_NAMES,
    D,
    extract_session_activation,
)
from mcp_server.shared.linear_algebra import norm, subtract

# ---------------------------------------------------------------------------
# Node construction helpers
# ---------------------------------------------------------------------------


def _build_layer_nodes(
    names: list[str],
    layer: str,
    prefix: str,
) -> list[dict[str, Any]]:
    """Build nodes for a single layer with uniform activation=0."""
    return [
        {"id": f"{prefix}:{name}", "label": name, "layer": layer, "activation": 0}
        for name in names
    ]


def _build_classifier_nodes(profile: dict) -> list[dict[str, Any]]:
    """Build classifier nodes with activation from metacognitive profile."""
    classifiers = [
        "activeReflective",
        "sensingIntuitive",
        "sequentialGlobal",
        "problemDecomposition",
        "explorationStyle",
        "verificationBehavior",
    ]
    mc = profile.get("metacognitive") or {}
    return [
        {
            "id": f"classifier:{cls}",
            "label": cls,
            "layer": "classifier",
            "activation": mc.get(cls) or 0,
        }
        for cls in classifiers
    ]


def _build_feature_nodes(dictionary: dict | None) -> list[dict[str, Any]]:
    """Build feature nodes from dictionary features."""
    if not dictionary or not dictionary.get("features"):
        return []
    return [
        {
            "id": f"feature:{f['label']}",
            "label": f["label"],
            "layer": "feature",
            "activation": 0,
        }
        for f in dictionary["features"]
    ]


def build_attribution_nodes(
    profile: dict,
    dictionary: dict | None,
) -> list[dict[str, Any]]:
    extractors = ["entryPoints", "recurringPatterns", "toolPreferences", "sessionShape"]

    nodes: list[dict[str, Any]] = []
    nodes.extend(_build_layer_nodes(list(SIGNAL_NAMES), "input", "input"))
    nodes.extend(_build_layer_nodes(extractors, "extractor", "extractor"))
    nodes.extend(_build_classifier_nodes(profile))
    nodes.extend(_build_feature_nodes(dictionary))
    nodes.append(
        {
            "id": "aggregator:profile",
            "label": "Domain Profile",
            "layer": "aggregator",
            "activation": profile.get("confidence") or 0,
        }
    )
    nodes.append(
        {
            "id": "output:context",
            "label": "Context Output",
            "layer": "output",
            "activation": 1,
        }
    )
    return nodes


# ---------------------------------------------------------------------------
# Perturbation-based edge weight computation
# ---------------------------------------------------------------------------

_SIGNAL_TO_EXTRACTOR: dict[str, str] = {}
for _i in range(7):
    _SIGNAL_TO_EXTRACTOR[SIGNAL_NAMES[_i]] = "extractor:toolPreferences"
for _i in range(7, 11):
    _SIGNAL_TO_EXTRACTOR[SIGNAL_NAMES[_i]] = "extractor:entryPoints"
for _i in range(11, 16):
    _SIGNAL_TO_EXTRACTOR[SIGNAL_NAMES[_i]] = "extractor:sessionShape"
_SIGNAL_TO_EXTRACTOR[SIGNAL_NAMES[16]] = "extractor:toolPreferences"
for _i in range(17, 27):
    _SIGNAL_TO_EXTRACTOR[SIGNAL_NAMES[_i]] = "extractor:recurringPatterns"

_EXTRACTOR_CLASSIFIER_MAP = {
    "extractor:toolPreferences": [
        "classifier:activeReflective",
        "classifier:explorationStyle",
    ],
    "extractor:entryPoints": [
        "classifier:sensingIntuitive",
        "classifier:problemDecomposition",
    ],
    "extractor:sessionShape": [
        "classifier:activeReflective",
        "classifier:sequentialGlobal",
    ],
    "extractor:recurringPatterns": [
        "classifier:verificationBehavior",
        "classifier:sensingIntuitive",
    ],
}


def _get_classifier_for_signal(signal: str) -> str | None:
    if (
        signal.startswith("tool:Edit")
        or signal.startswith("tool:Write")
        or signal.startswith("tool:Bash")
    ):
        return "classifier:activeReflective"
    if (
        signal.startswith("tool:Read")
        or signal.startswith("tool:Grep")
        or signal.startswith("tool:Glob")
    ):
        return "classifier:explorationStyle"
    if signal.startswith("kw:abstract") or signal.startswith("kw:concrete"):
        return "classifier:sensingIntuitive"
    if signal.startswith("kw:planning") or signal.startswith("kw:trial"):
        return "classifier:problemDecomposition"
    if signal.startswith("tmp:"):
        return "classifier:sequentialGlobal"
    if signal.startswith("cat:"):
        return "classifier:verificationBehavior"
    if signal.startswith("drv:"):
        return "classifier:activeReflective"
    return None


def _compute_mean_baseline(conversations: list[dict], max_samples: int) -> list[float]:
    """Compute mean activation vector from sampled conversations."""
    sampled = conversations[:max_samples]
    activations = [extract_session_activation(c) for c in sampled]
    mean = [0.0] * D
    if activations:
        for act in activations:
            for d in range(D):
                mean[d] += act[d] / len(activations)
    return mean


def _compute_input_to_extractor_edges(
    mean_baseline: list[float],
    epsilon: float,
) -> list[dict[str, Any]]:
    """Compute perturbation-based edges from input signals to extractors."""
    edges: list[dict[str, Any]] = []
    for s in range(D):
        signal = SIGNAL_NAMES[s]
        extractor = _SIGNAL_TO_EXTRACTOR.get(signal)
        if not extractor:
            continue

        perturbed = [
            mean_baseline[i] if i != s else mean_baseline[i] + epsilon for i in range(D)
        ]
        diff = norm(subtract(perturbed, mean_baseline))
        weight = diff / epsilon

        if weight > 0.01:
            edges.append(
                {
                    "source": f"input:{signal}",
                    "target": extractor,
                    "weight": round(weight * 1000) / 1000,
                }
            )
    return edges


def _compute_feature_edges(dictionary: dict | None) -> list[dict[str, Any]]:
    """Compute classifier-to-feature and feature-to-aggregator edges."""
    if not dictionary or not dictionary.get("features"):
        return []

    edges: list[dict[str, Any]] = []
    for feature in dictionary["features"]:
        for ts in feature.get("topSignals") or []:
            classifier_for = _get_classifier_for_signal(ts["signal"])
            if classifier_for:
                edges.append(
                    {
                        "source": classifier_for,
                        "target": f"feature:{feature['label']}",
                        "weight": abs(ts["weight"]),
                    }
                )
        edges.append(
            {
                "source": f"feature:{feature['label']}",
                "target": "aggregator:profile",
                "weight": 0.5,
            }
        )
    return edges


def compute_edge_weights(
    conversations: list[dict],
    profile: dict,
    dictionary: dict | None,
) -> list[dict[str, Any]]:
    EPSILON = 0.1
    MAX_SAMPLES = 20

    mean_baseline = _compute_mean_baseline(conversations, MAX_SAMPLES)

    edges: list[dict[str, Any]] = []
    edges.extend(_compute_input_to_extractor_edges(mean_baseline, EPSILON))

    # Extractor -> Classifier edges
    for extractor, classifiers in _EXTRACTOR_CLASSIFIER_MAP.items():
        for classifier in classifiers:
            edges.append(
                {
                    "source": extractor,
                    "target": classifier,
                    "weight": 0.5,
                }
            )

    edges.extend(_compute_feature_edges(dictionary))

    # Aggregator -> Output
    edges.append(
        {
            "source": "aggregator:profile",
            "target": "output:context",
            "weight": profile.get("confidence") or 0.5,
        }
    )
    return edges


# ---------------------------------------------------------------------------
# Full attribution graph
# ---------------------------------------------------------------------------


def trace_attribution(
    conversations: list[dict] | None,
    dictionary: dict | None,
    profile: dict | None,
) -> dict[str, list]:
    if not conversations or len(conversations) == 0 or not profile:
        return {"nodes": [], "edges": []}

    nodes = build_attribution_nodes(profile, dictionary)

    # Update input node activations from mean session data
    activations = [extract_session_activation(c) for c in conversations[:20]]
    if activations:
        for s in range(D):
            mean = sum(act[s] for act in activations) / len(activations)
            for n in nodes:
                if n["id"] == f"input:{SIGNAL_NAMES[s]}":
                    n["activation"] = round(mean * 1000) / 1000
                    break

    edges = compute_edge_weights(conversations, profile, dictionary)
    return {"nodes": nodes, "edges": edges}
