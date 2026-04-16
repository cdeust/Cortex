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
    "remember": {
        "properties": {
            "content": {"type": "string", "maxLength": 50000},
            "tags": {"type": "array"},
            "source": {"type": "string", "maxLength": 200},
            "domain": {"type": "string", "maxLength": 200},
            "directory": {"type": "string", "maxLength": 500},
            "agent_topic": {"type": "string", "maxLength": 200},
            "importance": {"type": "number"},
            "created_at": {"type": "string", "maxLength": 64},
            "initial_heat": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        },
        "required": ["content"],
    },
    "recall": {
        "properties": {
            "query": {"type": "string", "maxLength": 10000},
            "limit": {"type": "number"},
            "domain": {"type": "string", "maxLength": 200},
            "directory": {"type": "string", "maxLength": 500},
            "agent_topic": {"type": "string", "maxLength": 200},
        },
        "required": ["query"],
    },
    "wiki_write": {
        "properties": {
            "path": {"type": "string", "maxLength": 500},
            "content": {"type": "string", "maxLength": 200000},
            "mode": {"type": "string"},
            "title": {"type": "string", "maxLength": 500},
            "summary": {"type": "string", "maxLength": 5000},
            "body": {"type": "string", "maxLength": 200000},
            "tags": {"type": "array"},
        },
        "required": ["path"],
    },
    "wiki_read": {
        "properties": {
            "path": {"type": "string", "maxLength": 500},
        },
        "required": ["path"],
    },
    "wiki_list": {
        "properties": {
            "kind": {"type": "string", "maxLength": 20},
        },
        "required": [],
    },
    "wiki_link": {
        "properties": {
            "from_path": {"type": "string", "maxLength": 500},
            "to_path": {"type": "string", "maxLength": 500},
            "relation": {"type": "string", "maxLength": 40},
        },
        "required": ["from_path", "to_path", "relation"],
    },
    "wiki_adr": {
        "properties": {
            "title": {"type": "string", "maxLength": 500},
            "context": {"type": "string", "maxLength": 20000},
            "decision": {"type": "string", "maxLength": 20000},
            "consequences": {"type": "string", "maxLength": 20000},
            "status": {"type": "string", "maxLength": 40},
            "tags": {"type": "array"},
        },
        "required": ["title", "context", "decision", "consequences"],
    },
    "wiki_reindex": {
        "properties": {},
        "required": [],
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
    max_len = spec.get("maxLength")
    if max_len is not None and isinstance(value, str) and len(value) > max_len:
        raise ValidationError(
            f'Field "{field}" exceeds maximum length ({len(value)} > {max_len})',
            {"tool": tool_name, "field": field, "maxLength": max_len},
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
