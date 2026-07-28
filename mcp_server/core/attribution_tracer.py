"""Pipeline attribution graph via perturbation-based tracing.

Perturbs each input signal by +/-epsilon, re-runs downstream pure functions,
measures |output_perturbed - output_original| / epsilon. Samples at most 20 sessions.
"""

from __future__ import annotations

from mcp_server.core.sparse_dictionary_activation import (
    SIGNAL_NAMES,
    D,
    extract_session_activation,
)
from mcp_server.shared.linear_algebra import norm, subtract
from mcp_server.shared.types_features import (
    AttributionEdge,
    AttributionGraph,
    AttributionNode,
    FeatureDictionary,
)

# ---------------------------------------------------------------------------
# Node construction helpers
# ---------------------------------------------------------------------------


def _build_layer_nodes(
    names: list[str],
    layer: str,
    prefix: str,
) -> list[AttributionNode]:
    """Build nodes for a single layer with uniform activation=0."""
    return [
        AttributionNode(id=f"{prefix}:{name}", label=name, layer=layer, activation=0)
        for name in names
    ]


# Classifiers whose CognitiveStyle field is a continuous float score
# (types_profiles.CognitiveStyle.active_reflective/sensing_intuitive/
# sequential_global). These map directly onto AttributionNode.activation.
_NUMERIC_CLASSIFIERS = ["activeReflective", "sensingIntuitive", "sequentialGlobal"]

# Classifiers whose CognitiveStyle field is a categorical Literal[str]
# (types_profiles.CognitiveStyle.problem_decomposition/exploration_style/
# verification_behavior, e.g. "top-down"/"bottom-up"). These have no
# legitimate scalar magnitude, so activation stays 0.0 and the
# classification is carried in categoricalValue instead.
_CATEGORICAL_CLASSIFIERS = [
    "problemDecomposition",
    "explorationStyle",
    "verificationBehavior",
]


def _build_classifier_nodes(profile: dict) -> list[AttributionNode]:
    """Build classifier nodes with activation from metacognitive profile."""
    mc = profile.get("metacognitive") or {}

    nodes = [
        AttributionNode(
            id=f"classifier:{cls}",
            label=cls,
            layer="classifier",
            activation=mc.get(cls) or 0,
        )
        for cls in _NUMERIC_CLASSIFIERS
    ]
    nodes.extend(
        AttributionNode(
            id=f"classifier:{cls}",
            label=cls,
            layer="classifier",
            activation=0.0,
            categoricalValue=mc.get(cls),
        )
        for cls in _CATEGORICAL_CLASSIFIERS
    )
    return nodes


def _build_feature_nodes(dictionary: FeatureDictionary | None) -> list[AttributionNode]:
    """Build feature nodes from dictionary features."""
    if not dictionary or not dictionary.features:
        return []
    return [
        AttributionNode(
            id=f"feature:{f.label}",
            label=f.label,
            layer="feature",
            activation=0,
        )
        for f in dictionary.features
    ]


def build_attribution_nodes(
    profile: dict,
    dictionary: FeatureDictionary | None,
) -> list[AttributionNode]:
    extractors = ["entryPoints", "recurringPatterns", "toolPreferences", "sessionShape"]

    nodes: list[AttributionNode] = []
    nodes.extend(_build_layer_nodes(list(SIGNAL_NAMES), "input", "input"))
    nodes.extend(_build_layer_nodes(extractors, "extractor", "extractor"))
    nodes.extend(_build_classifier_nodes(profile))
    nodes.extend(_build_feature_nodes(dictionary))
    nodes.append(
        AttributionNode(
            id="aggregator:profile",
            label="Domain Profile",
            layer="aggregator",
            activation=profile.get("confidence") or 0,
        )
    )
    nodes.append(
        AttributionNode(
            id="output:context",
            label="Context Output",
            layer="output",
            activation=1,
        )
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


# source: pre-existing tuned value, extracted unchanged (#197 family 3);
# provenance not recorded at introduction
_MIN_EDGE_WEIGHT = 0.01  # perturbation weights at or below this are noise


def _compute_input_to_extractor_edges(
    mean_baseline: list[float],
    epsilon: float,
) -> list[AttributionEdge]:
    """Compute perturbation-based edges from input signals to extractors."""
    edges: list[AttributionEdge] = []
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

        if weight > _MIN_EDGE_WEIGHT:
            edges.append(
                AttributionEdge(
                    source=f"input:{signal}",
                    target=extractor,
                    weight=round(weight * 1000) / 1000,
                )
            )
    return edges


def _compute_feature_edges(
    dictionary: FeatureDictionary | None,
) -> list[AttributionEdge]:
    """Compute classifier-to-feature and feature-to-aggregator edges."""
    if not dictionary or not dictionary.features:
        return []

    edges: list[AttributionEdge] = []
    for feature in dictionary.features:
        for ts in feature.topSignals or []:
            classifier_for = _get_classifier_for_signal(ts.signal)
            if classifier_for:
                edges.append(
                    AttributionEdge(
                        source=classifier_for,
                        target=f"feature:{feature.label}",
                        weight=abs(ts.weight),
                    )
                )
        edges.append(
            AttributionEdge(
                source=f"feature:{feature.label}",
                target="aggregator:profile",
                weight=0.5,
            )
        )
    return edges


def compute_edge_weights(
    conversations: list[dict],
    profile: dict,
    dictionary: FeatureDictionary | None,
) -> list[AttributionEdge]:
    EPSILON = 0.1
    MAX_SAMPLES = 20

    mean_baseline = _compute_mean_baseline(conversations, MAX_SAMPLES)

    edges: list[AttributionEdge] = []
    edges.extend(_compute_input_to_extractor_edges(mean_baseline, EPSILON))

    # Extractor -> Classifier edges
    for extractor, classifiers in _EXTRACTOR_CLASSIFIER_MAP.items():
        for classifier in classifiers:
            edges.append(
                AttributionEdge(
                    source=extractor,
                    target=classifier,
                    weight=0.5,
                )
            )

    edges.extend(_compute_feature_edges(dictionary))

    # Aggregator -> Output
    edges.append(
        AttributionEdge(
            source="aggregator:profile",
            target="output:context",
            weight=profile.get("confidence") or 0.5,
        )
    )
    return edges


# ---------------------------------------------------------------------------
# Full attribution graph
# ---------------------------------------------------------------------------


def trace_attribution(
    conversations: list[dict] | None,
    dictionary: FeatureDictionary | None,
    profile: dict | None,
) -> AttributionGraph:
    if not conversations or len(conversations) == 0 or not profile:
        return AttributionGraph(nodes=[], edges=[])

    nodes = build_attribution_nodes(profile, dictionary)

    # Update input node activations from mean session data
    activations = [extract_session_activation(c) for c in conversations[:20]]
    if activations:
        for s in range(D):
            mean = sum(act[s] for act in activations) / len(activations)
            for n in nodes:
                if n.id == f"input:{SIGNAL_NAMES[s]}":
                    n.activation = round(mean * 1000) / 1000
                    break

    edges = compute_edge_weights(conversations, profile, dictionary)
    return AttributionGraph(nodes=nodes, edges=edges)
