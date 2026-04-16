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
            # ADR-0045 R2/R5 (fragility sweep v3.13.0 E3):
            # content maxLength tightened from 50_000 → 10_000 chars.
            # Taleb audit: a 100 KB content blob triggered ~100K fallback
            # regex scans in entity extraction plus OOM on the knowledge
            # graph path. 10 K is the bounded envelope; callers submitting
            # larger content get a ValidationError and must split upstream.
            "content": {"type": "string", "maxLength": 10000},
            # ADR-0045 R2 (fragility sweep v3.13.0 E4):
            # Bounded tags envelope — at most 20 tags, each ≤ 80 chars.
            # Prevents a caller from submitting a 10K-element tag list
            # (each tag becomes a tsvector lexeme, an FTS dictionary
            # entry, and a row in memory_entities) which would blow up
            # indexing cost without bounded benefit.
            "tags": {
                "type": "array",
                "maxItems": 20,
                "items": {"type": "string", "maxLength": 80},
            },
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


def _check_array_envelope(
    tool_name: str, field: str, value: list, spec: dict[str, Any]
) -> None:
    """Enforce ``maxItems`` + per-item ``items`` spec for an array field.

    precondition: ``value`` is a list (caller already type-checked).
    postcondition: if the array length exceeds ``maxItems`` or any item
    violates the per-item spec (type / maxLength), raises ValidationError
    with ``details`` carrying the bound and, for item failures, the
    offending index.

    Source: ADR-0045 R2 (fragility sweep E4) — bounded envelopes on all
    array inputs prevent pathological memory / indexing blowups.
    """
    max_items = spec.get("maxItems")
    if max_items is not None and len(value) > max_items:
        raise ValidationError(
            f'Field "{field}" exceeds maxItems ({len(value)} > {max_items})',
            {"tool": tool_name, "field": field, "maxItems": max_items},
        )

    item_spec = spec.get("items")
    if not item_spec:
        return

    item_type_name = item_spec.get("type")
    expected_item_type = _TYPE_CHECKS.get(item_type_name) if item_type_name else None
    item_max_len = item_spec.get("maxLength")

    for i, item in enumerate(value):
        if expected_item_type is not None and not isinstance(item, expected_item_type):
            got = type(item).__name__
            raise ValidationError(
                f'Field "{field}[{i}]" must be a {item_type_name}, got {got}',
                {
                    "tool": tool_name,
                    "field": field,
                    "index": i,
                    "expected": item_type_name,
                    "got": got,
                },
            )
        if (
            item_max_len is not None
            and isinstance(item, str)
            and len(item) > item_max_len
        ):
            raise ValidationError(
                f'Field "{field}[{i}]" exceeds maximum length '
                f"({len(item)} > {item_max_len})",
                {
                    "tool": tool_name,
                    "field": field,
                    "index": i,
                    "maxLength": item_max_len,
                },
            )


def _check_field_type(
    tool_name: str, field: str, value: Any, spec: dict[str, Any]
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
    if spec["type"] == "array" and isinstance(value, list):
        _check_array_envelope(tool_name, field, value, spec)


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
