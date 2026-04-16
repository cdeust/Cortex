"""Handler for the explore_features tool — interpretability exploration.

Modes: features, attribution, persona, crosscoder.
"""

from __future__ import annotations

from mcp_server.core.attribution_tracer import trace_attribution
from mcp_server.core.behavioral_crosscoder import (
    compare_feature_profiles,
    detect_persistent_features,
)
from mcp_server.core.persona_vector import (
    PERSONA_DIMENSIONS,
    build_persona_vector,
    compose_personas,
)
from mcp_server.core.sparse_dictionary import build_seed_dictionary
from mcp_server.infrastructure.profile_store import load_profiles

schema = {
    "description": (
        "Inspect the user's cognitive profile through one of four "
        "interpretability lenses (mechanistic-interpretability inspired, "
        "Bricken et al. 2023): `features` returns the active sparse-"
        "dictionary behavioral features for a domain; `attribution` "
        "traces which signals drove a recent decision through the "
        "pipeline; `persona` returns the 12D persona vector with "
        "drift-from-baseline; `crosscoder` compares two domains to "
        "detect persistent behavioral features. Use this when facing an "
        "unfamiliar pattern and you want a behavioral explanation. "
        "Distinct from `query_methodology` (full profile, not the "
        "interpretability internals), `get_methodology_graph` (graph "
        "for visualization, no per-feature inspection), and "
        "`list_domains` (overview, no analysis). Read-only on "
        "profiles.json. Latency <100ms. Returns mode-specific JSON: "
        "{dictionary | graph | persona | comparison}."
    ),
    "inputSchema": {
        "type": "object",
        "required": ["mode"],
        "properties": {
            "mode": {
                "type": "string",
                "description": (
                    "Which interpretability lens to apply. 'features' = sparse "
                    "dictionary activations; 'attribution' = decision tracing; "
                    "'persona' = 12D vector + drift; 'crosscoder' = "
                    "two-domain feature persistence."
                ),
                "enum": ["features", "attribution", "persona", "crosscoder"],
                "examples": ["features", "persona"],
            },
            "domain": {
                "type": "string",
                "description": "Cognitive domain to inspect. Omit for global aggregate where supported.",
                "examples": ["cortex", "auth-service"],
            },
            "compare_domain": {
                "type": "string",
                "description": "Second cognitive domain for the 'crosscoder' mode comparison.",
                "examples": ["ai-architect"],
            },
        },
    },
}


async def handler(args: dict) -> dict:
    mode = args.get("mode")
    domain = args.get("domain")
    compare_domain = args.get("compare_domain")

    profiles = load_profiles()

    if (
        not profiles
        or not profiles.get("domains")
        or len(profiles.get("domains", {})) == 0
    ):
        return {
            "status": "no_data",
            "message": "No profiles built yet. Run rebuild_profiles first.",
        }

    if mode == "features":
        return _handle_features(profiles)
    elif mode == "attribution":
        return _handle_attribution(profiles, domain)
    elif mode == "persona":
        return _handle_persona(profiles, domain)
    elif mode == "crosscoder":
        return _handle_crosscoder(profiles, domain, compare_domain)
    else:
        return {"status": "error", "message": f"Unknown mode: {mode}"}


def _handle_features(profiles: dict) -> dict:
    d = profiles.get("featureDictionary") or build_seed_dictionary()

    return {
        "status": "ok",
        "dictionary": {
            "K": d.get("K"),
            "D": d.get("D"),
            "sparsity": d.get("sparsity"),
            "learnedFromSessions": d.get("learnedFromSessions", 0),
            "features": [
                {
                    "index": f.get("index"),
                    "label": f.get("label"),
                    "description": f.get("description"),
                    "topSignals": f.get("topSignals"),
                }
                for f in (d.get("features") or [])
            ],
        },
        "persistentFeatures": profiles.get("persistentFeatures", []),
    }


def _handle_attribution(profiles: dict, domain: str | None) -> dict:
    domain_id = domain or next(iter(profiles.get("domains", {})), None)
    dp = profiles.get("domains", {}).get(domain_id) if domain_id else None

    if not dp:
        return {"status": "error", "message": f"Domain not found: {domain_id}"}

    d = profiles.get("featureDictionary") or build_seed_dictionary()
    graph = trace_attribution([], d, dp)

    # Enrich with stored activations
    if dp.get("featureActivations"):
        for node in graph.get("nodes", []):
            if (
                node.get("layer") == "feature"
                and node.get("label") in dp["featureActivations"]
            ):
                node["activation"] = dp["featureActivations"][node["label"]]

    return {
        "status": "ok",
        "domain": domain_id,
        "graph": graph,
    }


def _handle_persona(profiles: dict, domain: str | None) -> dict:
    if domain:
        dp = profiles.get("domains", {}).get(domain)
        if not dp:
            return {"status": "error", "message": f"Domain not found: {domain}"}

        persona = dp.get("personaVector") or build_persona_vector(dp)

        return {
            "status": "ok",
            "domain": domain,
            "persona": persona,
            "dimensions": PERSONA_DIMENSIONS,
        }

    # All domains + global
    domain_personas = {}
    vectors = []
    weights = []

    for d_id, dp in profiles.get("domains", {}).items():
        pv = dp.get("personaVector") or build_persona_vector(dp)
        domain_personas[d_id] = pv
        vectors.append(pv)
        weights.append(dp.get("sessionCount", 1))

    global_persona = compose_personas(vectors, weights)

    return {
        "status": "ok",
        "domains": domain_personas,
        "global": global_persona,
        "dimensions": PERSONA_DIMENSIONS,
    }


def _handle_crosscoder(
    profiles: dict, domain: str | None, compare_domain: str | None
) -> dict:
    d = profiles.get("featureDictionary") or build_seed_dictionary()

    if domain and compare_domain:
        dp_a = profiles.get("domains", {}).get(domain)
        dp_b = profiles.get("domains", {}).get(compare_domain)

        if not dp_a:
            return {"status": "error", "message": f"Domain not found: {domain}"}
        if not dp_b:
            return {"status": "error", "message": f"Domain not found: {compare_domain}"}

        comparison = compare_feature_profiles(
            dp_a.get("featureActivations", {}),
            dp_b.get("featureActivations", {}),
            d,
        )

        return {
            "status": "ok",
            "comparison": {
                "domainA": domain,
                "domainB": compare_domain,
                **comparison,
            },
        }

    # All persistent features
    persistent = profiles.get("persistentFeatures") or detect_persistent_features(
        profiles.get("domains", {}), d
    )

    return {
        "status": "ok",
        "persistentFeatures": persistent,
        "domainCount": len(profiles.get("domains", {})),
    }
