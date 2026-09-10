#!/usr/bin/env python3
"""Claude Code PostToolUse hook — captures significant tool outputs as
memories after each tool call, so graph ingestion is zero-friction.

Install via ``~/.claude/settings.json``'s PostToolUse hook pointed at
``python3 -m mcp_server.hooks.post_tool_capture``.

source: ADR-0495"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable
from typing import Any

from mcp_server.core.gist_extraction import (
    HIGH_VALUE_PATTERNS,
    extract_gist,
    format_artifact_pointer,
    needs_gist,
)
from mcp_server.hooks._capture_mode import capture_skip_reason
from mcp_server.hooks._capture_mode import HIGH_VALUE_TOOLS as _HIGH_VALUE_TOOLS
from mcp_server.shared.redaction import scrub_secrets

_LOG_PREFIX = "[cortex-post-tool-capture]"

# source: ADR-0495
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

# source: ADR-0495

# source: ADR-0495
_HIGH_VALUE_PATTERNS = HIGH_VALUE_PATTERNS


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
        # source: ADR-0495
        if len(output) < _MIN_OUTPUT_LENGTH:
            return False, "output_too_short"
        return True, f"network_tool:{tool_name}"

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
        return (
            f"**Glob:** `{tool_input.get('pattern') or ''}` "
            f"(root=`{tool_input.get('path') or ''}`)"
        )
    if tool_name == "Grep":
        return (
            f"**Grep:** `{tool_input.get('pattern') or ''}` "
            f"in `{tool_input.get('path') or ''}`"
        )
    return None


def _build_memory_content(
    tool_name: str,
    tool_input: dict,
    output: str,
    cwd: str,
) -> str:
    """Build a structured memory string.

    source: ADR-0495"""
    _ = cwd
    parts = [f"# Tool: {tool_name}"]
    ref = _reference_line(tool_name, tool_input)
    if ref:
        parts.append(ref)
    if tool_name in _LIGHT_VALUE_TOOLS:
        return "\n".join(parts)
    # Output is already Markdown-formatted (Bash/Edit/etc.) — don't
    # wrap. Otherwise wrap raw string output in a code fence so newlines
    # render as newlines.
    already_formatted = (
        "**stdout:**" in output
        or "**before:**" in output
        or output.startswith("**file:**")
    )
    if already_formatted:
        parts.append(f"\n## Output\n\n{output}")
    else:
        parts.append(f"\n**Output:**\n```\n{output}\n```")
    return "\n".join(parts)


def _gist_or_full(output: str) -> tuple[str, str | None]:
    """Return (body_output, pointer_line) for the memory body.

    Pre: output is the normalized tool output string.
    Post: when ``output`` fits GIST_BUDGET, returns (output, None) — stored as
    today. When it exceeds the budget, the FULL raw output is written to a
    content-addressed artifact and we return (gist, pointer_line) so the body
    carries a bounded gist plus a loadable pointer to the full artifact.

    Non-blocking contract: artifact write failure must NOT lose the capture —
    on any exception we fall back to (output, None) and log via _log, i.e. the
    legacy full-output behavior.
    """
    if not needs_gist(output):
        return output, None
    try:
        from mcp_server.infrastructure.artifact_store import store_artifact  # noqa: PLC0415 — hook latency boundary: the per-event hook process defers the handler/store stack (hook boot ~0.05 s vs ~0.6 s registry import, measured 2026-07-28)

        path = store_artifact(output)
    except Exception as exc:  # noqa: BLE001 — hook boundary — failure is logged to the hook log; the hook stays non-fatal
        _log(f"artifact write failed (non-fatal, full output kept): {exc}")
        return output, None
    pointer = format_artifact_pointer(str(path), len(output))
    return extract_gist(output), pointer


def _build_tags(tool_name: str, output: str) -> list[str]:
    """Build tags from tool name and output signals.

    source: ADR-0495"""
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
    return tags


def _normalize_output(raw_output: Any) -> str:
    """Normalize tool output to a HUMAN-READABLE string.

        Tool-response shapes handled here:

          * ``Bash``: ``{"stdout": "...", "stderr": "...", "interrupted": bool,
            ...}`` → renders stdout (and stderr if non-empty) as fenced
            sections with real newlines preserved.
          * ``Edit``/``Write``/``MultiEdit``: ``{"filePath": "...",
            "oldString": "...", "newString": "..."}`` → renders as a
            before/after section with real newlines.
          * Generic dict / list → json.dumps with ``indent=2`` so newlines
            between fields survive at least one level of structure.
          * Anything else → ``str()``.

    source: ADR-0495"""
    if isinstance(raw_output, dict):
        # Bash-shaped: stdout / stderr separated. Render each as its own
        # fenced section so multi-line output stays readable.
        if "stdout" in raw_output or "stderr" in raw_output:
            parts: list[str] = []
            stdout = str(raw_output.get("stdout") or "")
            stderr = str(raw_output.get("stderr") or "")
            if stdout.strip():
                parts.append(f"**stdout:**\n```\n{stdout.rstrip()}\n```")
            if stderr.strip():
                parts.append(f"**stderr:**\n```\n{stderr.rstrip()}\n```")
            interrupted = raw_output.get("interrupted")
            if interrupted:
                parts.append(f"**interrupted:** {interrupted}")
            if not parts:
                parts.append("_(no output)_")
            return "\n\n".join(parts)
        # Edit/Write-shaped: file_path + oldString/newString diff.
        if "filePath" in raw_output and (
            "oldString" in raw_output or "newString" in raw_output
        ):
            parts = [f"**file:** `{raw_output['filePath']}`"]
            old = raw_output.get("oldString")
            new = raw_output.get("newString")
            if old:
                parts.append(f"**before:**\n```\n{str(old).rstrip()}\n```")
            if new:
                parts.append(f"**after:**\n```\n{str(new).rstrip()}\n```")
            return "\n\n".join(parts)
        # Generic dict — indent=2 preserves field separation but still
        # escapes newlines inside string values. The wiki renderer can't
        # do better without a per-tool template; this is honest about
        # the shape.
        return json.dumps(raw_output, indent=2, default=str)
    if isinstance(raw_output, list):
        return json.dumps(raw_output, indent=2, default=str)
    return str(raw_output)


def _load_remember():
    """Import the async remember handler, fail loudly if the package
    isn't installed (the hook depends on the core distribution)."""
    try:
        import asyncio  # noqa: PLC0415 — optional-feature probe: ImportError here is a handled degraded mode
        from mcp_server.handlers.remember import handler  # noqa: PLC0415 — optional-feature probe: ImportError here is a handled degraded mode

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
    """Admit the unchanged remember payload to the resident worker."""
    from mcp_server.hooks.capture_dispatch import dispatch  # noqa: PLC0415 — hook filtering precedes all worker infrastructure imports

    payload: dict[str, object] = {
        "content": content,
        "tags": tags,
        "directory": cwd,
        "source": "post_tool_capture",
        # source: ADR-0495
        "origin_tool": tool_name,
        "write_class": "auto",
        "force": False,
    }
    if dispatch(payload):
        _log(f"queued {tool_name} for resident capture (persistence pending)")


# ── Periodic cascade advancement ──────────────────────────────────────
# Run cascade every N tool calls during active sessions.
# Biological basis: consolidation occurs during waking rest periods
# (Dewar et al. 2012), not only during sleep.


def _run_cascade() -> None:
    """Advance existing consolidation stages after a reserved interval."""
    from mcp_server.handlers.consolidation.cascade import (  # noqa: PLC0415 — hook latency boundary: the per-event hook process defers the handler/store stack (hook boot ~0.05 s vs ~0.6 s registry import, measured 2026-07-28)
        run_cascade_advancement,
    )
    from mcp_server.infrastructure.memory_store import get_shared_store  # noqa: PLC0415 — hook latency boundary: the per-event hook process defers the handler/store stack (hook boot ~0.05 s vs ~0.6 s registry import, measured 2026-07-28)

    store = get_shared_store()
    result = run_cascade_advancement(store)
    if "error" in result:
        raise RuntimeError(str(result["error"]))
    advanced = result.get("advanced", 0)
    if advanced > 0:
        _log(f"cascade: {advanced} memories advanced")


def _maybe_run_cascade(event: dict[str, Any]) -> None:
    """Count every tool call across hook processes; preserve pending work."""
    try:
        from mcp_server.infrastructure.hook_cascade_counter import advance_after_tool  # noqa: PLC0415 — W3-1b: excluded tools must return before importing infrastructure

        if advance_after_tool(event.get("transcript_path"), _run_cascade) == "pending":
            _log("cascade pending: execution lock busy or unavailable")
    except Exception as exc:  # noqa: BLE001 — hook boundary; the cause is logged and capture continues
        _log(f"cascade failed (non-fatal): {exc}")


def _capture_enabled(event: dict[str, Any]) -> bool:
    """Apply the explicit mode before output processing or cadence I/O."""
    # source: ADR-0495
    mode = os.environ.get("CORTEX_CAPTURE_MODE", "full")
    reason = capture_skip_reason(mode, event.get("tool_name", ""), _HIGH_VALUE_TOOLS)
    if reason is not None:
        _log(reason)
        return False
    return True


def _dispatch_with_store_cleanup(event: dict[str, Any]) -> None:
    """CLI lifecycle scope starts only after the mode admits this event."""
    if not _capture_enabled(event):
        return
    from mcp_server.hooks._store_lifecycle import close_shared_store_on_exit  # noqa: PLC0415 — W3-1b: no teardown store import for excluded events

    # source: ADR-0495
    with close_shared_store_on_exit():
        process_event(event)


def process_event(event: dict[str, Any]) -> None:
    """Process a PostToolUse event and optionally store a memory."""
    if not _capture_enabled(event):
        return
    tool_name = event.get("tool_name", "")
    tool_input = event.get("tool_input") or {}
    cwd = event.get("cwd", "")
    output = _normalize_output(event.get("tool_response") or "")

    # Periodic cascade check
    _maybe_run_cascade(event)

    should, reason = _should_capture(tool_name, tool_input, output)
    if not should:
        _log(f"skip {tool_name}: {reason}")
        return

    # Scrub secrets from the tool output BEFORE tagging, gisting, or
    # persisting.  This is the single choke point on the write path.
    # scrub_secrets covers: URL passwords, AWS keys, bearer tokens,
    # key=value secret assignments, and PEM private-key blocks.
    output = scrub_secrets(output)

    # Tags are derived from the FULL output so signal tags (error/test/
    # success) survive even when the body is gisted.
    tags = _build_tags(tool_name, output)
    body_output, pointer = _gist_or_full(output)
    content = _build_memory_content(tool_name, tool_input, body_output, cwd)
    if pointer:
        content = f"{content}\n\n{pointer}"
    # source: ADR-0495
    content = scrub_secrets(content)

    try:
        _store_memory(tool_name, content, tags, cwd)
    except Exception as exc:  # noqa: BLE001 — hook boundary — failure is logged to the hook log; the hook stays non-fatal
        _log(f"capture failed (non-fatal): {exc}")


def main(dispatch: Callable[[dict[str, Any]], None] | None = None) -> None:
    """Read a JSON event; the CLI supplies cleanup for admitted events."""
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

    (dispatch or process_event)(event)


if __name__ == "__main__":
    # No-op inside the headless wiki-authoring subprocess (see
    # _headless_guard): prevents recursion + memory pollution when
    # ``claude -p --setting-sources user`` loads the user hooks.
    from mcp_server.hooks._headless_guard import (
        exit_if_headless_authoring_child,
    )

    exit_if_headless_authoring_child()
    main(_dispatch_with_store_cleanup)
