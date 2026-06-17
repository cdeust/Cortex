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

from mcp_server.core.gist_extraction import (
    HIGH_VALUE_PATTERNS,
    extract_gist,
    needs_gist,
)
from mcp_server.shared.redaction import scrub_secrets

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

# 2026-05-17 (user directive: "Truncated info are prohibited"):
# auto-capture stores the FULL tool output. Truncation destroys the
# substrate halo retrieval needs — a 20k-char Edit diff cropped to 4k
# loses the actual code change. The directive itself anticipated
# "filesystem-backed references" as the remedy if the corpus grows too
# large. 2026-06-10 (user directive, tasks/bounded-io-phase2-design.md):
# outputs above GIST_BUDGET are now stored full to a content-addressed
# artifact file and the memory body keeps a deterministic gist + a pointer
# line. This is NOT truncation — nothing is dropped; the raw output is one
# `Read` away — and it removes the ts_rank_cd length-frequency bias (M2).

# Keywords that signal high-value content. Canonical home is
# core/gist_extraction.HIGH_VALUE_PATTERNS (moved there so the hook imports
# from core, the legal layer direction). Re-exported under the historical
# name for any in-repo reference.
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
    """Build a structured memory string. Light-value tools record only
    the input reference to keep writes <200ms.

    2026-05-17: ``_normalize_output`` now returns Markdown-ready text
    for dict tool responses (with its own fenced ``stdout:`` /
    ``stderr:`` sections). Detect that here and don't wrap it again —
    nested fences break rendering. Only wrap raw string output, which
    is the case for tools whose response is a flat string.
    """
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
        from mcp_server.infrastructure.artifact_store import store_artifact

        path = store_artifact(output)
    except Exception as exc:
        _log(f"artifact write failed (non-fatal, full output kept): {exc}")
        return output, None
    pointer = f"**Artifact:** `{path}` ({len(output)} chars full output)"
    return extract_gist(output), pointer


def _build_tags(tool_name: str, output: str) -> list[str]:
    """Build tags from tool name and output signals.

    2026-05-17: the ``decision`` tag was previously added whenever the
    raw tool output contained the substring "selected"/"switched"/etc.
    Edit/Bash dumps routinely contain those words inside diffs or stdout,
    so every auto-capture got promoted to wiki kind="adr" and rendered
    as ``Decision: <first line of dump>``. Real ADRs come from explicit
    ``remember`` calls with ``source="decision"``, not from PostToolUse
    keyword scanning — the tag is removed here.
    """
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

    2026-05-17 (user directive: "stdout should never be a single line,
    intelligible and readable documentation in natural way"). Previously
    every dict response went through ``json.dumps`` which encoded real
    newlines as the two-character ``\\n`` escape sequence — so a multi-
    line grep output rendered in the wiki as one literal-escape-laden
    string instead of a readable code block.

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
    """
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
    # Scrub the assembled content (catches secrets in the Bash command
    # reference line and any other structural fragments).
    content = scrub_secrets(content)

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
