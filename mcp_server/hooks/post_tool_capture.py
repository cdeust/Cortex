#!/usr/bin/env python3
"""Claude Code hook script for PostToolUse events.

Automatically captures significant tool outputs as memories after each
tool call. Makes memory ingestion zero-friction — no manual remember() calls
needed for important tool interactions.

Strategy
--------
Not all tool outputs are worth storing. We filter by:
  1. Tool type — some tools (Edit, Write, Bash) produce more signal-rich output
  2. Output length — very short outputs are usually noise
  3. Content signals — errors, decisions, file paths, test results
  4. Importance score — computed from thermodynamics module

Installation
------------
Add to ``~/.claude/settings.json``::

    {
        "hooks": {
            "PostToolUse": [{
                "type": "command",
                "command": "python3 -m mcp_server.hooks.post_tool_capture",
                "timeout": 10
            }]
        }
    }

Event schema (from Claude Code)
--------------------------------
{
    "session_id": "...",
    "tool_name": "Edit|Write|Bash|Read|...",
    "tool_input": {...},
    "tool_response": "...",
    "cwd": "/path/to/project"
}

Invariants
----------
- Non-blocking: exits quickly, errors logged to stderr but never raised
- Idempotent: repeated captures are gated by the predictive coding write gate
- Logs to stderr only
"""

from __future__ import annotations

import json
import sys
from typing import Any

_LOG_PREFIX = "[cortex-post-tool-capture]"

# Tools whose outputs are worth capturing
_HIGH_VALUE_TOOLS = {
    "Edit",
    "Write",
    "Bash",
    "NotebookEdit",
}

# Tools that may have value depending on content
# Note: Read, Glob, Grep are excluded — they are read-only tools whose
# output is just existing file contents. Capturing them wastes 8-25s on
# embedding model load + DB write with no memory value, and causes
# timeout errors in Claude Code's hook runner.
_CONDITIONAL_TOOLS = {
    "WebFetch",
    "WebSearch",
}

# Minimum output length to consider capturing (chars)
_MIN_OUTPUT_LENGTH = 50

# Maximum output length to store (chars) — truncate beyond this
_MAX_OUTPUT_LENGTH = 4096

# Keywords that signal high-value content
_HIGH_VALUE_PATTERNS = [
    "error",
    "exception",
    "traceback",
    "failed",
    "failure",
    "fixed",
    "resolved",
    "success",
    "deployed",
    "migrated",
    "decided",
    "chose",
    "switched",
    "selected",
    "created",
    "deleted",
    "moved",
    "refactored",
    "test",
    "assert",
    "pass",
    "fail",
    "warning",
    "deprecated",
]


def _log(msg: str) -> None:
    print(f"{_LOG_PREFIX} {msg}", file=sys.stderr)


def _should_capture(tool_name: str, tool_input: dict, output: str) -> tuple[bool, str]:
    """Decide whether to capture this tool interaction.

    Returns (should_capture, reason).
    """
    if len(output) < _MIN_OUTPUT_LENGTH:
        return False, "output_too_short"

    if tool_name in _HIGH_VALUE_TOOLS:
        return True, f"high_value_tool:{tool_name}"

    if tool_name in _CONDITIONAL_TOOLS:
        output_lower = output.lower()
        for kw in _HIGH_VALUE_PATTERNS:
            if kw in output_lower:
                return True, f"keyword:{kw}"
        # Also capture if the input references a file path
        if tool_name == "Bash":
            return True, "bash_output"
        return False, "no_signal_keywords"

    return False, f"low_value_tool:{tool_name}"


def _build_memory_content(
    tool_name: str,
    tool_input: dict,
    output: str,
    cwd: str,
) -> str:
    """Build a structured memory string from a tool interaction."""
    truncated = output[:_MAX_OUTPUT_LENGTH]
    if len(output) > _MAX_OUTPUT_LENGTH:
        truncated += f"\n... [truncated {len(output) - _MAX_OUTPUT_LENGTH} chars]"

    parts = [f"# Tool: {tool_name}"]

    # Add key input fields (not the full input — too noisy)
    if tool_name in {"Edit", "Write"} and "file_path" in tool_input:
        parts.append(f"**File:** `{tool_input['file_path']}`")
    elif tool_name == "Bash" and "command" in tool_input:
        cmd = str(tool_input["command"])[:200]
        parts.append(f"**Command:** `{cmd}`")
    elif tool_name == "Read" and "file_path" in tool_input:
        parts.append(f"**Read:** `{tool_input['file_path']}`")

    parts.append(f"\n**Output:**\n```\n{truncated}\n```")

    return "\n".join(parts)


def _build_tags(tool_name: str, output: str) -> list[str]:
    """Build tags from tool name and output signals."""
    tags = ["auto-captured", f"tool:{tool_name.lower()}"]
    output_lower = output.lower()
    if (
        "error" in output_lower
        or "exception" in output_lower
        or "traceback" in output_lower
    ):
        tags.append("error")
    if "test" in output_lower and ("pass" in output_lower or "fail" in output_lower):
        tags.append("test-result")
    if any(kw in output_lower for kw in ("fixed", "resolved", "success")):
        tags.append("success")
    if any(kw in output_lower for kw in ("decided", "chose", "switched", "selected")):
        tags.append("decision")
    return tags


def _normalize_output(raw_output: Any) -> str:
    """Normalize tool output to a string."""
    if isinstance(raw_output, (dict, list)):
        return json.dumps(raw_output, default=str)
    return str(raw_output)


def _store_memory(tool_name: str, content: str, tags: list[str], cwd: str) -> None:
    """Store a memory via the remember handler."""
    try:
        import asyncio

        from mcp_server.handlers.remember import handler as remember_handler
    except ImportError as exc:
        missing = str(exc).replace("No module named ", "").strip("'")
        print(
            f"Cortex hook: missing dependency '{missing}'. "
            f'Run: pip install -e "$(dirname $0)/../.."',
            file=sys.stderr,
        )
        sys.exit(1)

    result = asyncio.run(
        remember_handler(
            {
                "content": content,
                "tags": tags,
                "directory": cwd,
                "source": "post_tool_capture",
                "force": False,
            }
        )
    )

    if result.get("stored"):
        _log(
            f"captured {tool_name} → memory_id={result.get('memory_id')} "
            f"(surprise={result.get('surprise', 0):.3f})"
        )
    else:
        _log(f"gated {tool_name}: {result.get('reason', 'below_threshold')}")


def process_event(event: dict[str, Any]) -> None:
    """Process a PostToolUse event and optionally store a memory."""
    tool_name = event.get("tool_name", "")
    tool_input = event.get("tool_input") or {}
    cwd = event.get("cwd", "")
    output = _normalize_output(event.get("tool_response") or "")

    should, reason = _should_capture(tool_name, tool_input, output)
    if not should:
        _log(f"skip {tool_name}: {reason}")
        return

    content = _build_memory_content(tool_name, tool_input, output, cwd)
    tags = _build_tags(tool_name, output)

    try:
        _store_memory(tool_name, content, tags, cwd)
    except Exception as exc:
        _log(f"capture failed (non-fatal): {exc}")


def main() -> None:
    """Entry point — read JSON event from stdin and process it."""
    if sys.stdin.isatty():
        _log("No stdin data (TTY mode), exiting")
        return

    raw = sys.stdin.read().strip()
    if not raw:
        _log("Empty stdin, exiting")
        return

    try:
        event = json.loads(raw)
    except json.JSONDecodeError as exc:
        _log(f"Failed to parse event JSON: {exc}")
        return

    process_event(event)


if __name__ == "__main__":
    main()
