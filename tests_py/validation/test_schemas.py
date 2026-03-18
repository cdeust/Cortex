"""Tests for mcp_server.validation.schemas — tool argument validation."""

import pytest

from mcp_server.errors import ValidationError
from mcp_server.validation.schemas import validate_tool_args


class TestValidateToolArgs:
    def test_passes_valid_args(self):
        result = validate_tool_args(
            "record_session_end",
            {
                "session_id": "abc-123",
                "domain": "web",
            },
        )
        assert result["session_id"] == "abc-123"
        assert result["domain"] == "web"

    def test_raises_for_missing_required_field(self):
        with pytest.raises(ValidationError, match="session_id"):
            validate_tool_args("record_session_end", {})

    def test_raises_when_required_field_is_none(self):
        with pytest.raises(ValidationError):
            validate_tool_args("record_session_end", {"session_id": None})

    def test_raises_for_string_type_mismatch(self):
        with pytest.raises(ValidationError, match="string"):
            validate_tool_args(
                "record_session_end",
                {
                    "session_id": "ok",
                    "domain": 123,
                },
            )

    def test_raises_for_number_type_mismatch(self):
        with pytest.raises(ValidationError, match="number"):
            validate_tool_args(
                "record_session_end",
                {
                    "session_id": "ok",
                    "duration": "not-a-number",
                },
            )

    def test_raises_for_boolean_type_mismatch(self):
        with pytest.raises(ValidationError, match="boolean"):
            validate_tool_args("rebuild_profiles", {"force": "yes"})

    def test_raises_for_array_type_mismatch(self):
        with pytest.raises(ValidationError, match="array"):
            validate_tool_args(
                "record_session_end",
                {
                    "session_id": "ok",
                    "tools_used": "not-an-array",
                },
            )

    def test_applies_default_values(self):
        result = validate_tool_args("rebuild_profiles", {})
        assert result["force"] is False

    def test_does_not_override_provided_with_defaults(self):
        result = validate_tool_args("rebuild_profiles", {"force": True})
        assert result["force"] is True

    def test_passes_through_for_unknown_tool(self):
        args = {"foo": "bar", "baz": 42}
        result = validate_tool_args("unknown_tool", args)
        assert result == args

    def test_returns_empty_for_unknown_tool_with_no_args(self):
        result = validate_tool_args("unknown_tool", None)
        assert result == {}

    def test_handles_no_required_fields_no_args(self):
        result = validate_tool_args("list_domains", {})
        assert result == {}

    def test_only_includes_known_properties(self):
        result = validate_tool_args(
            "rebuild_profiles",
            {
                "domain": "web",
                "force": True,
                "extra_field": "should not appear",
            },
        )
        assert result["domain"] == "web"
        assert result["force"] is True
        assert "extra_field" not in result
