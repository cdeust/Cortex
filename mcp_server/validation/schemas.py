"""Input validation schemas for MCP tool arguments.

Lightweight schema validation: define expected types and required fields per
tool, validate before handler execution, throw ValidationError on failure.
Unknown tool names pass through (no schema = no validation).
"""

from __future__ import annotations

from typing import Any

from mcp_server.errors import ValidationError

# Schema definitions per tool.
# Each property has a type and optional default.
SCHEMAS: dict[str, dict] = {
    "query_methodology": {
        "properties": {
            "cwd": {"type": "string"},
            "project": {"type": "string"},
            "first_message": {"type": "string"},
        },
        "required": [],
    },
    "detect_domain": {
        "properties": {
            "cwd": {"type": "string"},
            "project": {"type": "string"},
            "first_message": {"type": "string"},
        },
        "required": [],
    },
    "rebuild_profiles": {
        "properties": {
            "domain": {"type": "string"},
            "force": {"type": "boolean", "default": False},
        },
        "required": [],
    },
    "list_domains": {
        "properties": {},
        "required": [],
    },
    "record_session_end": {
        "properties": {
            "session_id": {"type": "string"},
            "domain": {"type": "string"},
            "tools_used": {"type": "array"},
            "duration": {"type": "number"},
            "turn_count": {"type": "number"},
            "keywords": {"type": "array"},
            "cwd": {"type": "string"},
            "project": {"type": "string"},
        },
        "required": ["session_id"],
    },
    "get_methodology_graph": {
        "properties": {
            "domain": {"type": "string"},
        },
        "required": [],
    },
    "open_visualization": {
        "properties": {
            "domain": {"type": "string"},
        },
        "required": [],
    },
    "explore_features": {
        "properties": {
            "mode": {"type": "string"},
            "domain": {"type": "string"},
            "compare_domain": {"type": "string"},
        },
        "required": ["mode"],
    },
    "run_pipeline": {
        "properties": {
            "codebase_path": {"type": "string"},
            "task_path": {"type": "string"},
            "context_path": {"type": "string"},
            "github_repo": {"type": "string"},
            "server": {"type": "string", "default": "ai-architect"},
            "max_findings": {"type": "number", "default": 5},
        },
        "required": ["codebase_path", "task_path"],
    },
    "codebase_analyze": {
        "properties": {
            "directory": {"type": "string"},
            "languages": {"type": "array"},
            "max_files": {"type": "number"},
            "max_file_size_kb": {"type": "number"},
            "incremental": {"type": "boolean"},
            "dry_run": {"type": "boolean"},
            "domain": {"type": "string"},
        },
        "required": [],
    },
}

_TYPE_CHECKS: dict[str, type | tuple[type, ...]] = {
    "string": str,
    "number": (int, float),
    "boolean": bool,
    "array": list,
}


def _check_field_type(
    tool_name: str, field: str, value: Any, spec: dict[str, str]
) -> None:
    """Validate a single field's type, raising ValidationError on mismatch."""
    expected_type = _TYPE_CHECKS.get(spec["type"])
    if expected_type is None:
        return

    # In Python, bool is a subclass of int — reject bools for number type
    if spec["type"] == "number" and isinstance(value, bool):
        raise ValidationError(
            f'Field "{field}" must be a number, got bool',
            {"tool": tool_name, "field": field, "expected": "number", "got": "bool"},
        )
    if not isinstance(value, expected_type):
        got = type(value).__name__
        raise ValidationError(
            f'Field "{field}" must be a {spec["type"]}, got {got}',
            {"tool": tool_name, "field": field, "expected": spec["type"], "got": got},
        )


def validate_tool_args(tool_name: str, args: dict[str, Any] | None) -> dict[str, Any]:
    """Validate and sanitize tool arguments against the schema.

    Returns validated arguments with defaults applied.
    Raises ValidationError for missing required fields or type mismatches.
    Unknown tool names pass through unchanged.
    """
    schema = SCHEMAS.get(tool_name)
    if schema is None:
        return args if args is not None else {}

    safe_args = args if args is not None else {}
    result: dict[str, Any] = {}

    for field in schema["required"]:
        if safe_args.get(field) is None:
            raise ValidationError(
                f"Missing required field: {field}",
                {"tool": tool_name, "field": field},
            )

    for field, spec in schema["properties"].items():
        value = safe_args.get(field)
        if value is None:
            if "default" in spec:
                result[field] = spec["default"]
            continue
        _check_field_type(tool_name, field, value, spec)
        result[field] = value

    return result
