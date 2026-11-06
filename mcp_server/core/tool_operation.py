"""The common operation an observed tool name stands for, across hosts.

A session's ``toolsUsed`` keeps each host's native tool names: Claude Code
records ``Edit``/``Write``/``Read``/``Grep``, a Codex rollout records
``apply_patch`` and ``exec`` (``infrastructure/transcript_rollout.py``).
Those names stay as recorded, for provenance. A behavioral signal that asks
"was this an edit or a read" asks it here instead of matching Claude names,
so an equivalent explicit edit counts the same from either host (issue #727).

Only operations a tool name makes explicit are classified:

- ``apply_patch`` carries file edits by construction; the hook path already
  turns it into Edit/Write events (``hooks/host_patch.py``), so the
  transcript path classifies it as an edit too.
- ``exec`` runs an arbitrary program whose effect is not in its name: it
  stays unclassified (``None``) rather than being guessed into a read.

source: issue #727; ADR-1081 (rollout tool names); ADR-0228 (the Edit/Write
and Read/Grep groups the style observation already used).
"""

from __future__ import annotations

EDIT = "edit"
READ = "read"

_OPERATION_BY_TOOL: dict[str, str] = {
    "Edit": EDIT,
    "Write": EDIT,
    "apply_patch": EDIT,
    "Read": READ,
    "Grep": READ,
}


def operation_of(tool_name: str) -> str | None:
    """``EDIT``, ``READ``, or ``None`` when the name does not make it explicit."""
    return _OPERATION_BY_TOOL.get(tool_name)


def count_operation(tools_used: list[str], operation: str) -> int:
    """How many entries of ``tools_used`` stand for ``operation``."""
    return sum(1 for tool in tools_used if operation_of(tool) == operation)
