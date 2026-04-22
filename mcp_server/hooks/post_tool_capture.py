#!/usr/bin/env python3
"""Claude Code PostToolUse hook — captures significant tool outputs as
memories after each tool call, so graph ingestion is zero-friction.

Filters: tool kind (high-value vs light-value vs conditional), output
length, content-signal keywords. High-value tools (Edit/Write/Bash/
MultiEdit/NotebookEdit) store the full truncated output; light-value
tools (Read/NotebookRead/Glob/Grep) record only the input reference to
keep writes <200ms. Invariants: non-blocking, idempotent via the
predictive-coding write gate, stderr-only logging.

Install via ``~/.claude/settings.json``'s PostToolUse hook pointed at
``python3 -m mcp_server.hooks.post_tool_capture``.
"""

from __future__ import annotations

import json
import sys
from typing import Any

_LOG_PREFIX = "[cortex-post-tool-capture]"

# Tools whose FULL output (truncated to _MAX_OUTPUT_LENGTH) is stored.
_HIGH_VALUE_TOOLS = {
    "Edit",
    "Write",
    "Bash",
    "MultiEdit",
    "NotebookEdit",
}

# Tools we capture for graph visibility only. We record the input
# reference (file_path / pattern / command / URL) but NOT the tool output
# — that keeps the write <200ms even on read-heavy loops and sidesteps
# the embedding-model timeout concern that previously excluded Read /
# Glob / Grep entirely. The workflow graph wants to see every file
# Claude touched, not just the ones it modified; this makes that
# practical for live sessions, not only historical JSONL.
_LIGHT_VALUE_TOOLS = {
    "Read",
    "NotebookRead",
    "Glob",
    "Grep",
}

# Tools that may have value depending on content
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

    Returns (should_capture, reason). Light-value tools bypass the
    output-length check — we capture their input reference even when
    the tool returned nothing.
    """
    if tool_name in _HIGH_VALUE_TOOLS:
        if len(output) < _MIN_OUTPUT_LENGTH:
            return False, "output_too_short"
        return True, f"high_value_tool:{tool_name}"

    if tool_name in _LIGHT_VALUE_TOOLS:
        return True, f"light_value_tool:{tool_name}"

    if tool_name in _CONDITIONAL_TOOLS:
        output_lower = output.lower()
        for kw in _HIGH_VALUE_PATTERNS:
            if kw in output_lower:
                return True, f"keyword:{kw}"
        if tool_name == "Bash":
            return True, "bash_output"
        return False, "no_signal_keywords"

    return False, f"low_value_tool:{tool_name}"


def _reference_line(tool_name: str, tool_input: dict) -> str | None:
    """Marker line parsed by workflow_graph_source_pg to extract paths."""
    if tool_name in {"Edit", "Write", "MultiEdit"}:
        fp = tool_input.get("file_path")
        return f"**File:** `{fp}`" if fp else None
    if tool_name == "NotebookEdit":
        fp = tool_input.get("notebook_path")
        return f"**File:** `{fp}`" if fp else None
    if tool_name == "Bash":
        cmd = str(tool_input.get("command") or "")[:200]
        return f"**Command:** `{cmd}`" if cmd else None
    if tool_name in {"Read", "NotebookRead"}:
        fp = tool_input.get("file_path") or tool_input.get("notebook_path")
        return f"**Read:** `{fp}`" if fp else None
    if tool_name == "Glob":
        return (f"**Glob:** `{tool_input.get('pattern') or ''}` "
                f"(root=`{tool_input.get('path') or ''}`)")
    if tool_name == "Grep":
        return (f"**Grep:** `{tool_input.get('pattern') or ''}` "
                f"in `{tool_input.get('path') or ''}`")
    return None


def _build_memory_content(
    tool_name: str, tool_input: dict, output: str, cwd: str,
) -> str:
    """Build a structured memory string. Light-value tools record only
    the input reference to keep writes <200ms."""
    _ = cwd
    parts = [f"# Tool: {tool_name}"]
    ref = _reference_line(tool_name, tool_input)
    if ref:
        parts.append(ref)
    if tool_name in _LIGHT_VALUE_TOOLS:
        return "\n".join(parts)
    truncated = output[:_MAX_OUTPUT_LENGTH]
    if len(output) > _MAX_OUTPUT_LENGTH:
        truncated += f"\n... [truncated {len(output) - _MAX_OUTPUT_LENGTH} chars]"
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


def _load_remember():
    """Import the async remember handler, fail loudly if the package
    isn't installed (the hook depends on the core distribution)."""
    try:
        import asyncio
        from mcp_server.handlers.remember import handler
        return asyncio, handler
    except ImportError as exc:
        missing = str(exc).replace("No module named ", "").strip("'")
        print(
            f"Cortex hook: missing dependency '{missing}'. "
            f'Run: pip install -e "$(dirname $0)/../.."',
            file=sys.stderr,
        )
        sys.exit(1)


def _store_memory(tool_name: str, content: str, tags: list[str], cwd: str) -> None:
    """Store a memory via the remember handler."""
    asyncio, remember_handler = _load_remember()
    result = asyncio.run(remember_handler({
        "content": content, "tags": tags, "directory": cwd,
        "source": "post_tool_capture", "force": False,
    }))
    if result.get("stored"):
        _log(
            f"captured {tool_name} → memory_id={result.get('memory_id')} "
            f"(surprise={result.get('surprise', 0):.3f})"
        )
    else:
        _log(f"gated {tool_name}: {result.get('reason', 'below_threshold')}")


# ── Periodic cascade advancement ──────────────────────────────────────
# Run cascade every N tool calls during active sessions.
# Biological basis: consolidation occurs during waking rest periods
# (Dewar et al. 2012), not only during sleep.

_CASCADE_INTERVAL = 20  # Run cascade every 20 tool calls
_tool_call_counter = 0


def _maybe_run_cascade() -> None:
    """Run cascade advancement if enough tool calls have accumulated."""
    global _tool_call_counter
    _tool_call_counter += 1
    if _tool_call_counter < _CASCADE_INTERVAL:
        return
    _tool_call_counter = 0

    try:
        from mcp_server.handlers.consolidation.cascade import (
            run_cascade_advancement,
        )
        from mcp_server.infrastructure.memory_store import MemoryStore

        store = MemoryStore()
        result = run_cascade_advancement(store)
        advanced = result.get("advanced", 0)
        if advanced > 0:
            _log(f"cascade: {advanced} memories advanced")
    except Exception as exc:
        _log(f"cascade failed (non-fatal): {exc}")


def process_event(event: dict[str, Any]) -> None:
    """Process a PostToolUse event and optionally store a memory."""
    tool_name = event.get("tool_name", "")
    tool_input = event.get("tool_input") or {}
    cwd = event.get("cwd", "")
    output = _normalize_output(event.get("tool_response") or "")

    # Periodic cascade check
    _maybe_run_cascade()

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
