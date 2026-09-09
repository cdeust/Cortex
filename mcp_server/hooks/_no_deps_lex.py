"""Pure lexical detection for the ``--no-deps`` install invariant.

Shared by ``no_deps_gate`` (the PreToolUse hook) and
``scripts/check_no_deps_invariant.py`` (the repo-wide CI scan), so there is
exactly one definition of "violates the invariant" for the two layers to
agree on — see ADR-1062.

No I/O in this module: the caller reads the file or reconstructs the
candidate content; this module only classifies text, same discipline as
``scripts/craftsmanship_rules.py``.
"""

from __future__ import annotations

import re

# A physical line ending in a bare backslash continues the shell statement
# on the next line (bash, Dockerfile ``RUN``, and YAML ``run:`` blocks all
# use this convention) — see Dockerfile:93 and scripts/setup.sh:224-225.
_CONTINUATION_RE = re.compile(r"\\[ \t]*$")

# Statement separators within one already-continuation-merged logical line.
# ``|`` is deliberately excluded: every scoped call site pipes into a
# command, never chains a second pip invocation after one, and treating it
# as a separator would truncate a still-open command mid-scan.
_SEGMENT_SPLIT_RE = re.compile(r"&&|;")

# A ``-r`` argument naming a generated, hash-pinned constraint file: every
# scoped call site either sits under a ``requirements/`` directory
# (``requirements/setup.txt``) or is named ``requirements.txt`` verbatim
# (``.devcontainer/Dockerfile``) — never a hand-written package list.
_REQUIREMENTS_R_RE = re.compile(r"(?:^|\s)-r\s+\S*\brequirements\S*\.txt")

REQUIRE_HASHES = "--require-hashes"
NO_DEPS = "--no-deps"


def _merge_continuations(text: str) -> list[tuple[int, str]]:
    """(1-based start line, logical line) pairs, joining ``\\``-continued
    lines into the one shell statement they actually form."""
    result: list[tuple[int, str]] = []
    buf: list[str] = []
    start: int | None = None
    for lineno, raw in enumerate(text.splitlines(), start=1):
        if start is None:
            start = lineno
        stripped = raw.rstrip()
        if _CONTINUATION_RE.search(stripped):
            buf.append(_CONTINUATION_RE.sub("", stripped))
            continue
        buf.append(raw)
        result.append((start, " ".join(buf)))
        buf = []
        start = None
    if buf:
        result.append((start, " ".join(buf)))
    return result


def find_violations(content: str) -> list[tuple[int, str]]:
    """(line, command) for each logical command that pairs ``--require-hashes``
    with a ``-r <...requirements...txt>`` install but omits ``--no-deps``.

    Precondition: ``content`` is the full text of a file that may embed
    shell commands (a script body, a Dockerfile ``RUN``, or a YAML ``run:``
    block).
    Postcondition: returns one entry per offending command, in file order;
    returns ``[]`` when every such command in ``content`` also carries
    ``--no-deps`` (including when neither flag appears at all).
    """
    violations: list[tuple[int, str]] = []
    for start_line, logical in _merge_continuations(content):
        for segment in _SEGMENT_SPLIT_RE.split(logical):
            if REQUIRE_HASHES not in segment:
                continue
            if not _REQUIREMENTS_R_RE.search(segment):
                continue
            if NO_DEPS in segment:
                continue
            violations.append((start_line, segment.strip()))
    return violations
