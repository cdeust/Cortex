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
from mcp_server.handlers._tool_meta import READ_ONLY
from mcp_server.infrastructure.profile_store import load_profiles
from mcp_server.infrastructure.scanner import discover_conversations_for_projects
from mcp_server.shared.types_features import FeatureDictionary, PersistentFeature

# Bound on how many real sessions the attribution mode fetches from disk.
# source: measured 2026-07-10 on this environment -- a discover_conversations_
# for_projects() scan capped at 20 sessions from one project directory takes
# ~12ms (vs ~270ms for an unscoped full-history scan), keeping the handler
# within the tool schema's documented "Latency <100ms" budget. Matches the
# pre-existing MAX_SAMPLES truncation already applied downstream in
# attribution_tracer.py (conversations[:20]), so fetching more here would
# only be discarded by trace_attribution before use.
ATTRIBUTION_SAMPLE_LIMIT = 20

schema = {
    "title": "Explore features (interpretability lens)",
    "annotations": READ_ONLY,
    "outputSchema": {
        "type": "object",
        "required": ["mode"],
        "properties": {
            "mode": {
                "type": "string",
                "enum": ["features", "attribution", "persona", "crosscoder"],
            },
            "features": {
                "type": "array",
                "description": (
                    "Active sparse-dictionary behavioral features (mode=features)."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "activation": {"type": "number"},
                    },
                },
            },
            "attribution": {
                "type": "array",
                "description": (
                    "Signal → decision attribution edges (mode=attribution)."
                ),
                "items": {"type": "object"},
            },
            "persona": {
                "type": "object",
                "description": (
                    "12-dimensional persona vector + drift-from-baseline "
                    "(mode=persona)."
                ),
            },
            "crosscoder": {
                "type": "object",
                "description": (
                    "Cross-domain persistent-feature comparison (mode=crosscoder)."
                ),
            },
        },
    },
    "description": (
        "Inspect the user's cognitive profile through one of four "
        "interpretability lenses (mechanistic-interpretability inspired, "
        "Bricken et al. 2023): `features` returns the active sparse-"
        "dictionary behavioral features for a domain; `attribution` "
        "perturbation-traces which input signals drove the domain's "
        "profile, sampling up to 20 of that domain's own recent sessions "
        "from disk (empty graph if the domain has no indexed sessions -- "
        "run rebuild_profiles first); `persona` returns the 12D persona "
        "vector with drift-from-baseline; `crosscoder` compares two "
        "domains to detect persistent behavioral features. Use this when "
        "facing an unfamiliar pattern and you want a behavioral "
        "explanation. Distinct from `query_methodology` (full profile, not the "
        "interpretability internals) and `list_domains` (overview, no "
        "analysis). Read-only on "
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
                "description": (
                    "Cognitive domain to inspect. Omit for global aggregate where "
                    "supported."
                ),
                "examples": ["cortex", "auth-service"],
            },
            "compare_domain": {
                "type": "string",
                "description": (
                    "Second cognitive domain for the 'crosscoder' mode comparison."
                ),
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
    if mode == "attribution":
        return _handle_attribution(profiles, domain)
    if mode == "persona":
        return _handle_persona(profiles, domain)
    if mode == "crosscoder":
        return _handle_crosscoder(profiles, domain, compare_domain)
    return {"status": "error", "message": f"Unknown mode: {mode}"}


def _resolve_feature_dictionary(profiles: dict) -> FeatureDictionary:
    """Validate the disk-persisted featureDictionary, or fall back to the seed.

    profiles.get("featureDictionary") is JSON loaded from profiles.json
    (written by profile_assembler.py) — an untyped dict at this exact
    boundary. Validate it into FeatureDictionary here, once, so every
    downstream consumer in this handler works with the typed model.
    """
    raw = profiles.get("featureDictionary")
    if raw:
        return FeatureDictionary.model_validate(raw)
    return build_seed_dictionary()


def _handle_features(profiles: dict) -> dict:
    d = _resolve_feature_dictionary(profiles)

    return {
        "status": "ok",
        "dictionary": {
            "K": d.K,
            "D": d.D,
            "sparsity": d.sparsity,
            "learnedFromSessions": d.learnedFromSessions,
            "features": [
                {
                    "index": f.index,
                    "label": f.label,
                    "description": f.description,
                    "topSignals": [ts.model_dump() for ts in f.topSignals],
                }
                for f in d.features
            ],
        },
        "persistentFeatures": profiles.get("persistentFeatures", []),
    }


def _fetch_attribution_conversations(dp: dict) -> list[dict]:
    """Fetch the real sessions attribution tracing should perturb.

    Precondition: dp is a domain-profile dict as stored in profiles.json
    (may or may not carry a "projects" list, depending on how it was
    built/mocked). Postcondition: returns at most ATTRIBUTION_SAMPLE_LIMIT
    real conversation records scanned from dp's own project directories
    only; returns [] (no disk I/O) when dp has no known projects, matching
    trace_attribution's documented "empty graph without conversations"
    contract rather than fabricating sessions.
    """
    project_ids = dp.get("projects") or []
    if not project_ids:
        return []
    return discover_conversations_for_projects(project_ids, ATTRIBUTION_SAMPLE_LIMIT)


def _handle_attribution(profiles: dict, domain: str | None) -> dict:
    domain_id = domain or next(iter(profiles.get("domains", {})), None)
    dp = profiles.get("domains", {}).get(domain_id) if domain_id else None

    if not dp:
        return {"status": "error", "message": f"Domain not found: {domain_id}"}

    d = _resolve_feature_dictionary(profiles)
    conversations = _fetch_attribution_conversations(dp)
    graph = trace_attribution(conversations, d, dp)

    # Enrich with stored activations
    if dp.get("featureActivations"):
        for node in graph.nodes:
            if node.layer == "feature" and node.label in dp["featureActivations"]:
                node.activation = dp["featureActivations"][node.label]

    return {
        "status": "ok",
        "domain": domain_id,
        "graph": graph.model_dump(),
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


def _resolve_persistent_features(
    profiles: dict, d: FeatureDictionary
) -> list[PersistentFeature]:
    """Validate the disk-persisted persistentFeatures, or compute them fresh.

    Same boundary-validation pattern as _resolve_feature_dictionary: the
    disk-loaded list is untyped JSON; validate once here so the caller
    always holds list[PersistentFeature].
    """
    raw = profiles.get("persistentFeatures")
    if raw:
        return [PersistentFeature.model_validate(pf) for pf in raw]
    return detect_persistent_features(profiles.get("domains", {}), d)


def _handle_crosscoder(
    profiles: dict, domain: str | None, compare_domain: str | None
) -> dict:
    d = _resolve_feature_dictionary(profiles)

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
    persistent = _resolve_persistent_features(profiles, d)

    return {
        "status": "ok",
        "persistentFeatures": [pf.model_dump() for pf in persistent],
        "domainCount": len(profiles.get("domains", {})),
    }
