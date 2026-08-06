"""Deterministic gist extraction for oversized auto-captured tool output.

Pure logic, zero I/O. The hook (post_tool_capture) and the import/backfill
handlers store full raw output to a filesystem artifact and keep only a
bounded *gist* in the memory body, plus a pointer line to the artifact.
Nothing is dropped — the raw output is one ``Read`` away — so this satisfies
the 2026-05-17 "no truncation of available information" directive while
removing the ts_rank_cd length-frequency bias that makes a 120 KB Bash dump
outrank a curated lesson (M2 root cause, write side — see
docs/provenance/bounded-io-phase2-design.md F3).

Gist composition is deterministic (no LLM): a head slice + the high-value
signal lines + a tail slice, filled sequentially within the budget. The
40/60/100 fill boundaries are structural (readability of the helper), not
tuned — any monotone split keeps the same retrieval hooks (error/traceback/
failed/pass lines) inside the gist regardless of where they sit in the dump.

The high-value pattern list is owned here (core) so the hook imports it from
core rather than the reverse — a layer inversion (hooks → core is allowed;
core → hooks is not). post_tool_capture re-exports it for backward use.
"""

from __future__ import annotations

import re

# source: measured p90 curated memory length, production DB 2026-06-10
# (3,041 chars, n=68) — see docs/provenance/bounded-io-phase2-design.md. Makes
# auto-captures size-comparable to curated content, removing the
# ts_rank_cd length-frequency bias (M2/H5).
GIST_BUDGET = 3000

# Sequential-fill boundaries as fractions of the budget. Structural
# (readability), not tuned: head fills to _HEAD_FRACTION, signal lines fill
# to _SIGNAL_FRACTION, tail fills the remainder. Any monotone split keeps
# the signal lines (the retrieval hooks) inside the gist.
_HEAD_FRACTION = 0.40
_SIGNAL_FRACTION = 0.60

# Keywords that signal high-value content. Canonical home: this list was
# moved here from post_tool_capture._HIGH_VALUE_PATTERNS so the hook imports
# it from core (hooks → core is the legal direction) and the gist signal
# lines stay consistent with what the hook treats as high-value.
HIGH_VALUE_PATTERNS = [
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


# ── Artifact pointer: ONE definition, used by every writer and the reader ──
#
# The pointer line is the only link from a memory body to its full raw content
# on disk. It was previously built by two duplicated f-strings: one in
# hooks/post_tool_capture._gist_or_full, one in handlers/backfill_helpers. That
# meant no reader could parse it safely — a drift in either writer would break
# the parse silently. The forget handler must find and remove that artifact,
# see issue #366, so the format is defined once here, in the layer both
# writers already import.
_ARTIFACT_LABEL = "**Artifact:**"

# Matches the line format emitted by format_artifact_pointer. The path group is
# non-greedy and backtick-delimited, so a path containing spaces is preserved
# and a trailing "(N chars ...)" suffix is never swallowed into it.
_ARTIFACT_POINTER_RE = re.compile(
    r"\*\*Artifact:\*\*\s+`(?P<path>[^`]+)`",
)


def format_artifact_pointer(path: str, char_count: int) -> str:
    """Render the pointer line linking a memory body to its raw artifact.

    Pre: ``path`` is the artifact path as a string; ``char_count`` is the length
    of the full raw output the artifact holds.
    Post: returns a single line that ``parse_artifact_pointer`` recovers
    ``path`` from. This is the ONLY place the format is defined.
    """
    return f"{_ARTIFACT_LABEL} `{path}` ({char_count} chars full output)"


def parse_artifact_pointer(content: str) -> str | None:
    """Recover the artifact path from a memory body, or None when absent.

    Pre: ``content`` is a memory body (may be empty, may contain no pointer).
    Post: returns the path string from the FIRST pointer line produced by
    ``format_artifact_pointer``, else None. Never raises — a body with no
    pointer, or a malformed one, yields None so callers treat "no artifact" and
    "unparseable" identically (both mean: nothing safe to delete).
    """
    if not content:
        return None
    match = _ARTIFACT_POINTER_RE.search(content)
    if match is None:
        return None
    path = match.group("path").strip()
    return path or None


def needs_gist(output: str) -> bool:
    """True when output exceeds the gist budget and should be artifact-backed.

    Pre: output is a string.
    Post: returns ``len(output) > GIST_BUDGET``.
    """
    return len(output) > GIST_BUDGET


def _elision(kept: int, total: int) -> str:
    """Elision marker line recording how much of the output the gist kept."""
    return f"… [gist: {kept} of {total} chars — full output in artifact] …"


def _is_signal_line(line: str) -> bool:
    """True when a line contains any high-value pattern (case-insensitive)."""
    lower = line.lower()
    return any(kw in lower for kw in HIGH_VALUE_PATTERNS)


def extract_gist(output: str, budget: int = GIST_BUDGET) -> str:
    """Deterministic head + signal + tail gist of ``output`` within ``budget``.

    Pre: output is a string; budget is a positive int.
    Post: never raises; returns a string whose length is ≤
    ``budget`` + a small fixed overhead (two elision marker lines). When
    ``output`` already fits the budget it is returned unchanged. Signal lines
    (matching HIGH_VALUE_PATTERNS) that fall outside the head/tail windows are
    retained as long as the signal budget allows — an error line buried in the
    middle of a long dump survives.

    Composition (sequential fill, structural boundaries):
      1. head lines until cumulative length reaches _HEAD_FRACTION · budget
      2. signal lines not already taken, until _SIGNAL_FRACTION · budget
      3. tail lines (from the end) until the remaining budget is exhausted
    Order in the result is head → signal → tail with an elision marker at each
    gap so the reader knows content was elided.
    """
    if len(output) <= budget:
        return output

    lines = output.splitlines()
    taken: set[int] = set()

    head_parts, head_end, used = _fill_head(lines, int(budget * _HEAD_FRACTION), taken)
    signal_parts, used = _fill_signal(
        lines, head_end, int(budget * _SIGNAL_FRACTION), used, taken
    )
    tail_parts, used = _fill_tail(lines, head_end, budget, used, taken)

    segments: list[str] = []
    if head_parts:
        segments.append("\n".join(head_parts))
    if signal_parts:
        segments.append("\n".join(signal_parts))
    # One elision marker before the tail records what the gist dropped.
    segments.append(_elision(used, len(output)))
    if tail_parts:
        segments.append("\n".join(tail_parts))
    return "\n".join(segments)


def _fill_head(
    lines: list[str], limit: int, taken: set[int]
) -> tuple[list[str], int, int]:
    """Take leading lines until cumulative length reaches ``limit``.

    Returns (parts, head_end_index, used_chars). Mutates ``taken``.
    """
    parts: list[str] = []
    used = 0
    head_end = 0
    for idx, line in enumerate(lines):
        if used + len(line) + 1 > limit:
            break
        parts.append(line)
        taken.add(idx)
        used += len(line) + 1
        head_end = idx + 1
    return parts, head_end, used


def _fill_signal(
    lines: list[str], start: int, limit: int, used: int, taken: set[int]
) -> tuple[list[str], int]:
    """Take signal lines after the head window until ``limit``. Mutates taken."""
    parts: list[str] = []
    for idx in range(start, len(lines)):
        line = lines[idx]
        if idx in taken or not _is_signal_line(line):
            continue
        if used + len(line) + 1 > limit:
            break
        parts.append(line)
        taken.add(idx)
        used += len(line) + 1
    return parts, used


def _fill_tail(
    lines: list[str], start: int, budget: int, used: int, taken: set[int]
) -> tuple[list[str], int]:
    """Take trailing lines (from the end) until ``budget``. Mutates taken."""
    parts: list[str] = []
    for idx in range(len(lines) - 1, start - 1, -1):
        line = lines[idx]
        if idx in taken:
            continue
        if used + len(line) + 1 > budget:
            break
        parts.append(line)
        taken.add(idx)
        used += len(line) + 1
    parts.reverse()
    return parts, used
