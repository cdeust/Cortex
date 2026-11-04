"""Output-schema validation for explore_features (#680 regression guard).

A strict MCP client validates every tool result against the tool's declared
``outputSchema``. Before #680, ``outputSchema.required`` listed ``mode`` but no
return path set it, so every call failed client-side. Each return path below
runs through ``jsonschema.validate``, as test_checkpoint_output_schema.py does
for #99.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import jsonschema
import pytest

from mcp.server.mcpserver import MCPServer

from mcp_server import tool_registry_core as registry
from mcp_server.core.behavioral_crosscoder import detect_persistent_features
from mcp_server.core.persona_vector import PERSONA_DIMENSIONS
from mcp_server.core.sparse_dictionary import build_seed_dictionary
from mcp_server.handlers import explore_features
from mcp_server.handlers.explore_features import handler, schema
from mcp_server.handlers.explore_features_schema import MODES

_OUTPUT_SCHEMA = schema["outputSchema"]
_SEED = build_seed_dictionary()
_LABELS = [f.label for f in _SEED.features]
_DOMAINS = {
    "a": {"label": "A", "sessionCount": 3, "featureActivations": {_LABELS[0]: 0.8}},
    "b": {"label": "B", "sessionCount": 1, "featureActivations": {_LABELS[0]: 0.7}},
}
# Computed: the handler builds the dictionary, the persistent features and the
# personas. Stored: it reads them back as profile_assembler.py writes them.
_COMPUTED = {"domains": _DOMAINS}
_STORED = {
    "domains": {
        d_id: {**dp, "personaVector": {dim: 0.5 for dim in PERSONA_DIMENSIONS}}
        for d_id, dp in _DOMAINS.items()
    },
    "featureDictionary": _SEED.model_dump(by_alias=True),
    "persistentFeatures": [
        pf.model_dump() for pf in detect_persistent_features(_DOMAINS, _SEED)
    ],
}
_PROFILES = [
    pytest.param(_COMPUTED, id="computed"),
    pytest.param(_STORED, id="stored"),
]


def _run(args: dict, profiles: dict | None) -> dict:
    with (
        patch(
            "mcp_server.handlers.explore_features.load_profiles",
            return_value=profiles,
        ),
        patch(
            "mcp_server.handlers.explore_features._fetch_attribution_conversations",
            return_value=[],
        ),
    ):
        return asyncio.run(handler(args))


_PATHS = [
    ({"mode": "features"}, "ok"),
    ({"mode": "attribution"}, "ok"),
    ({"mode": "attribution", "domain": "a"}, "ok"),
    ({"mode": "attribution", "domain": "missing"}, "error"),
    ({"mode": "persona"}, "ok"),
    ({"mode": "persona", "domain": "a"}, "ok"),
    ({"mode": "persona", "domain": "missing"}, "error"),
    ({"mode": "crosscoder"}, "ok"),
    ({"mode": "crosscoder", "domain": "a", "compare_domain": "b"}, "ok"),
    ({"mode": "crosscoder", "domain": "missing", "compare_domain": "b"}, "error"),
    ({"mode": "crosscoder", "domain": "a", "compare_domain": "missing"}, "error"),
]


@pytest.mark.parametrize("profiles", _PROFILES)
@pytest.mark.parametrize(("args", "status"), _PATHS)
def test_every_profile_path_validates_and_echoes_mode(args, status, profiles):
    result = _run(args, profiles)
    jsonschema.validate(result, _OUTPUT_SCHEMA)
    assert result["mode"] == args["mode"]
    assert result["status"] == status
    assert set(result) <= set(_OUTPUT_SCHEMA["properties"]), args


@pytest.mark.parametrize(
    ("mode", "profiles"),
    [
        # mode=features only reads stored persistentFeatures; crosscoder
        # reads them back or computes them.
        pytest.param("features", _STORED, id="features-stored"),
        pytest.param("crosscoder", _STORED, id="crosscoder-stored"),
        pytest.param("crosscoder", _COMPUTED, id="crosscoder-computed"),
    ],
)
def test_persistent_feature_items_are_validated_non_empty(mode, profiles):
    """The items rule is checked against real entries, not only ``[]``."""
    result = _run({"mode": mode}, profiles)
    jsonschema.validate(result, _OUTPUT_SCHEMA)
    assert result["persistentFeatures"]
    assert result["persistentFeatures"][0]["label"] == _LABELS[0]


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("profiles", [None, {}, {"domains": {}}])
def test_no_data_path_validates_and_echoes_mode(mode, profiles):
    result = _run({"mode": mode}, profiles)
    jsonschema.validate(result, _OUTPUT_SCHEMA)
    assert result == {
        "mode": mode,
        "status": "no_data",
        "message": "No profiles built yet. Run rebuild_profiles first.",
    }


def _registered_server() -> MCPServer:
    server = MCPServer(name="explore-features-schema-test")
    registry._register_explore_features(server)
    return server


def test_registered_input_schema_publishes_the_mode_enum():
    """Clients read the wrapper signature, not schema["inputSchema"]."""
    tools = asyncio.run(_registered_server().list_tools())
    (tool,) = [t for t in tools if t.name == "explore_features"]
    published = tool.input_schema["properties"]["mode"]["enum"]
    declared = schema["inputSchema"]["properties"]["mode"]["enum"]
    assert published == declared == _OUTPUT_SCHEMA["properties"]["mode"]["enum"]
    assert published == list(MODES)


def test_registered_tool_rejects_an_unknown_mode_before_the_handler():
    """An unknown mode is an input-validation error, so the handler's
    ValueError and safe_handler's substring classifier are never reached."""
    with (
        patch("mcp_server.handlers.explore_features.handler") as called,
        pytest.raises(Exception, match="extension"),
    ):
        asyncio.run(
            _registered_server().call_tool("explore_features", {"mode": "extension"})
        )
    called.assert_not_called()


def test_handlers_cover_every_mode():
    assert set(explore_features._HANDLERS) == set(MODES)


def test_description_states_the_real_persona_dimension_count():
    assert f"{len(PERSONA_DIMENSIONS)}D persona vector" in schema["description"]
    assert "12D" not in schema["description"]
