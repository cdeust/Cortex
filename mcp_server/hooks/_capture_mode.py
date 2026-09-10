"""PostToolUse capture policy, evaluated before any memory infrastructure."""

from __future__ import annotations

from collections.abc import Collection

# source: ADR-0477
HIGH_VALUE_TOOLS = {"Edit", "Write", "Bash", "MultiEdit", "NotebookEdit"}


def capture_skip_reason(
    mode: str, tool_name: str, write_tools: Collection[str]
) -> str | None:
    """Return a visible skip reason, or None to retain the existing pipeline.

    source: ADR-0477"""
    if mode == "full":
        return None
    if mode == "off":
        return "CORTEX_CAPTURE_MODE=off"
    if mode == "writes-only":
        return None if tool_name in write_tools else "CORTEX_CAPTURE_MODE=writes-only"
    return (
        f"invalid CORTEX_CAPTURE_MODE={mode!r}; expected full, writes-only or off; "
        "capture skipped"
    )
