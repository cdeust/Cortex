"""Sourced capture transport budgets; safe to import before store/model setup."""

from __future__ import annotations

import json
import math
import os

from mcp_server.infrastructure.capture_transport import Limits
from mcp_server.shared.content_hardening import CONTENT_MAX_BYTES

# source: ADR-0489
DIRECTORY_CHARS = 500
# source: ADR-0489
TAG_COUNT = 20
# source: ADR-0489
TAG_CHARS = 80
# source: ADR-0489
DEFAULT_IDLE_SECONDS = 300.0
# source: ADR-0489
TRANSPORT_SECONDS = 10.0
# source: ADR-0489
JSON_ESCAPE_BYTES = 6
CAPTURE_TOOLS = {
    "Edit",
    "Write",
    "Bash",
    "MultiEdit",
    "NotebookEdit",
    "Read",
    "NotebookRead",
    "Glob",
    "Grep",
    "WebFetch",
    "WebSearch",
}  # source: ADR-0489


def limits() -> Limits:
    idle = float(os.environ.get("CORTEX_CAPTURE_IDLE_SECONDS", DEFAULT_IDLE_SECONDS))
    if not math.isfinite(idle) or idle <= 0:
        raise ValueError("CORTEX_CAPTURE_IDLE_SECONDS must be finite and positive")
    # source: ADR-0489
    skeleton = {
        "content": "",
        "tags": [""] * TAG_COUNT,
        "directory": "",
        "source": "post_tool_capture",
        "origin_tool": "NotebookEdit",
        "write_class": "auto",
        "force": False,
    }
    envelope = len(json.dumps(skeleton, separators=(",", ":")).encode("utf-8"))
    strings = CONTENT_MAX_BYTES + DIRECTORY_CHARS + TAG_COUNT * TAG_CHARS
    return Limits(JSON_ESCAPE_BYTES * strings + envelope, TRANSPORT_SECONDS, idle)


def validate_payload(payload: dict[str, object]) -> None:
    expected = {
        "content",
        "tags",
        "directory",
        "source",
        "origin_tool",
        "write_class",
        "force",
    }
    if set(payload) != expected or payload["source"] != "post_tool_capture":
        raise ValueError("invalid capture payload schema or source")
    if payload["write_class"] != "auto" or payload["force"] is not False:
        raise ValueError("capture must retain the auto write gate")
    origin_tool = payload["origin_tool"]
    if not isinstance(origin_tool, str) or origin_tool not in CAPTURE_TOOLS:
        raise ValueError("unknown producing capture tool")
    content, directory, tags = (
        payload.get("content"),
        payload.get("directory"),
        payload.get("tags"),
    )
    if not isinstance(content, str) or len(content.encode("utf-8")) > CONTENT_MAX_BYTES:
        raise ValueError("capture content exceeds the existing content-byte envelope")
    if not isinstance(directory, str) or len(directory) > DIRECTORY_CHARS:
        raise ValueError("capture directory exceeds the remember schema envelope")
    if not isinstance(tags, list) or len(tags) > TAG_COUNT:
        raise ValueError("capture tags exceed the remember schema envelope")
    if any(not isinstance(tag, str) or len(tag) > TAG_CHARS for tag in tags):
        raise ValueError("capture tag exceeds the remember schema envelope")
