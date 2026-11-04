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

from mcp_server.core.persona_vector import PERSONA_DIMENSIONS
from mcp_server.handlers.explore_features import handler, schema
from mcp_server.handlers.explore_features_schema import MODES

_OUTPUT_SCHEMA = schema["outputSchema"]
_PROFILES = {
    "domains": {
        "a": {"label": "A", "sessionCount": 3, "featureActivations": {"x": 0.4}},
        "b": {"label": "B", "sessionCount": 1, "featureActivations": {"x": 0.1}},
    }
}


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


@pytest.mark.parametrize(("args", "status"), _PATHS)
def test_every_profile_path_validates_and_echoes_mode(args, status):
    result = _run(args, _PROFILES)
    jsonschema.validate(result, _OUTPUT_SCHEMA)
    assert result["mode"] == args["mode"]
    assert result["status"] == status


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


def test_declared_payload_keys_are_the_returned_ones():
    """Every key an ok path returns is a declared property, so the schema
    documents the real shape rather than names no path sets."""
    declared = set(_OUTPUT_SCHEMA["properties"])
    for args, status in _PATHS:
        if status == "ok":
            assert set(_run(args, _PROFILES)) <= declared, args


def test_input_and_output_mode_enums_match():
    input_enum = schema["inputSchema"]["properties"]["mode"]["enum"]
    assert input_enum == _OUTPUT_SCHEMA["properties"]["mode"]["enum"] == list(MODES)


def test_description_states_the_real_persona_dimension_count():
    assert f"{len(PERSONA_DIMENSIONS)}D persona vector" in schema["description"]
    assert "12D" not in schema["description"]
