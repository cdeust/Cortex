"""MCP tool schema for `explore_features` — extracted from explore_features.py.

The schema dict is pure data. explore_features.py imports `schema` and `MODES`
from here; `schema` is the module-level export the MCP server registration
reads.

The output schema describes the keys the handler actually returns (#680): a
strict client validates structured content against it, so a required key the
handler never sets makes every call fail client-side.
"""

from __future__ import annotations

from typing import Literal, get_args

from mcp_server.core.persona_vector import PERSONA_DIMENSIONS
from mcp_server.handlers._tool_meta import READ_ONLY

# The registered wrapper types `mode` with ExploreMode, so the MCP SDK publishes
# the enum and rejects any other string before the handler runs.
ExploreMode = Literal["features", "attribution", "persona", "crosscoder"]
MODES: tuple[str, ...] = get_args(ExploreMode)

_PERSONA_DIM = len(PERSONA_DIMENSIONS)

_OUTPUT_PROPERTIES = {
    "mode": {
        "type": "string",
        "enum": list(MODES),
        "description": "The lens that produced this response, echoed from the call.",
    },
    "status": {"type": "string", "enum": ["ok", "no_data", "error"]},
    "message": {
        "type": "string",
        "description": "Why there is no result (status=no_data or status=error).",
    },
    "dictionary": {
        "type": "object",
        "description": "Sparse behavioral feature dictionary (mode=features).",
    },
    "persistentFeatures": {
        "type": "array",
        "items": {"type": "object"},
        "description": (
            "Features persistent across domains (mode=features; "
            "mode=crosscoder without two domains)."
        ),
    },
    "domain": {
        "type": "string",
        "description": "Inspected domain (mode=attribution; mode=persona with domain).",
    },
    "graph": {
        "type": "object",
        "description": "Signal → feature → decision graph (mode=attribution).",
    },
    "persona": {
        "type": "object",
        "description": (
            f"{_PERSONA_DIM}-dimensional persona vector of one domain "
            "(mode=persona with domain)."
        ),
    },
    "domains": {
        "type": "object",
        "description": "Persona vector per domain (mode=persona without domain).",
    },
    "global": {
        "type": "object",
        "description": (
            "Session-weighted composition of every domain's persona vector "
            "(mode=persona without domain)."
        ),
    },
    "dimensions": {
        "type": "array",
        "items": {"type": "string"},
        "description": "Persona dimension names in vector order (mode=persona).",
    },
    "comparison": {
        "type": "object",
        "description": (
            "Feature comparison of domain and compare_domain (mode=crosscoder)."
        ),
    },
    "domainCount": {
        "type": "integer",
        "description": "Domains in the profile (mode=crosscoder without two domains).",
    },
}

schema = {
    "title": "Explore features (interpretability lens)",
    "annotations": READ_ONLY,
    "outputSchema": {
        "type": "object",
        "required": ["mode", "status"],
        "properties": _OUTPUT_PROPERTIES,
    },
    "description": (
        "Inspect the user's cognitive profile through one of four "
        "interpretability lenses (mechanistic-interpretability inspired, "
        "Bricken et al. 2023): `features` returns the sparse behavioral "
        "feature dictionary and the cross-domain persistent features; "
        "`attribution` "
        "perturbation-traces which input signals drove the domain's "
        "profile, sampling up to 20 of that domain's own recent sessions "
        "from disk (empty graph if the domain has no indexed sessions -- "
        "run rebuild_profiles first); `persona` returns the "
        f"{_PERSONA_DIM}D persona vector of one domain, or of every domain "
        "with their session-weighted composition; `crosscoder` compares two "
        "domains (shared and unique active features), or without both returns "
        "the features persistent across all domains. Use this when "
        "facing an unfamiliar pattern and you want a behavioral "
        "explanation. Distinct from `query_methodology` (full profile, not the "
        "interpretability internals) and `list_domains` (overview, no "
        "analysis). Read-only on "
        "profiles.json. Latency <100ms. Every response carries `mode` and "
        "`status`, plus the lens's payload: "
        "{dictionary | graph | persona | domains | comparison | "
        "persistentFeatures}. An unknown mode is a tool error."
    ),
    "inputSchema": {
        "type": "object",
        "required": ["mode"],
        "properties": {
            "mode": {
                "type": "string",
                "description": (
                    "Which interpretability lens to apply. 'features' = sparse "
                    "feature dictionary and persistent features; 'attribution' "
                    "= decision tracing; "
                    f"'persona' = {_PERSONA_DIM}D vector; 'crosscoder' = active "
                    "features shared by and unique to domain and "
                    "compare_domain, or the features persistent across all "
                    "domains without both."
                ),
                "enum": list(MODES),
                "examples": ["features", "persona"],
            },
            "domain": {
                "type": "string",
                "description": (
                    "Cognitive domain to inspect. 'attribution' uses the first "
                    "domain when omitted (the response's `domain` names it); "
                    "'persona' returns every domain when omitted; 'crosscoder' "
                    "uses it only with compare_domain; 'features' ignores it."
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
