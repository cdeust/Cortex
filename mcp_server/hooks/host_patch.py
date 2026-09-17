"""Translate a Codex ``apply_patch`` command into Edit/Write-shaped events.

Ported from ``hooks/lib/host_events.py`` in the same owner's
zetetic-team-subagents repository (commit 4c2bc9b, PR #139), MIT licensed:

    MIT License

    Copyright (c) 2026 Clement Deust

    Permission is hereby granted, free of charge, to any person obtaining a
    copy of this software and associated documentation files (the
    "Software"), to deal in the Software without restriction, including
    without limitation the rights to use, copy, modify, merge, publish,
    distribute, sublicense, and/or sell copies of the Software, and to
    permit persons to whom the Software is furnished to do so, subject to
    the following conditions: the above copyright notice and this
    permission notice shall be included in all copies or substantial
    portions of the Software. THE SOFTWARE IS PROVIDED "AS IS", WITHOUT
    WARRANTY OF ANY KIND, EXPRESS OR IMPLIED.

Patch grammar follows Codex ``apply_patch`` (Begin/End Patch, file
operations, ``@@`` context anchors and End of File). This module never
writes to the filesystem: it only reads preimages to compute the resulting
text, and it fails closed on ambiguous or missing context so it never
approves content different from the prospective edit.

source: learn.chatgpt.com/docs/hooks (read 2026-09-17), cross-checked
against zetetic-team-subagents hooks/lib/host_events.py and
hooks/lib/gate_targets.py, which run live under Codex.
"""

from __future__ import annotations

from pathlib import Path

from mcp_server.hooks.host_event_errors import HostEventError

_ADD, _DELETE, _UPDATE = "Add File", "Delete File", "Update File"
_MOVE_PREFIX = "*** Move to: "
# An envelope needs at least its Begin/End markers plus one operation header.
_MIN_ENVELOPE_LINES = 3


def _resolve(value: object, cwd: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HostEventError("Missing file path")
    return str((Path(cwd) / Path(value)).resolve())


def _shaped(event: dict, tool_name: str, path: str, **fields: object) -> dict:
    return {
        **event,
        "tool_name": tool_name,
        "tool_input": {"file_path": path, **fields},
    }


def _read_preimage(path: str, state: dict) -> str:
    if path not in state:
        try:
            state[path] = Path(path).read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise HostEventError(f"Cannot read patch preimage {path}: {exc}") from exc
    if state[path] is None:
        raise HostEventError(f"Patch references deleted file: {path}")
    return state[path]


def _match_unique(
    lines: list[str], expected: list[str], start: int, end: bool = False
) -> int:
    positions = [
        i
        for i in range(start, len(lines) - len(expected) + 1)
        if lines[i : i + len(expected)] == expected
        and (not end or i + len(expected) == len(lines))
    ]
    if len(positions) != 1:
        reason = "ambiguous" if positions else "missing"
        raise HostEventError(
            f"Patch preimage is {reason}; exact unique context required"
        )
    return positions[0]


def _read_hunk(body: list[str], index: int) -> tuple[list[str], list[str], int, bool]:
    old: list[str] = []
    new: list[str] = []
    while index < len(body) and not body[index].startswith(("@@", "***")):
        line = body[index]
        if not line or line[0] not in " +-":
            raise HostEventError(f"Invalid patch hunk line: {line!r}")
        if line[0] in " -":
            old.append(line[1:])
        if line[0] in " +":
            new.append(line[1:])
        index += 1
    if not old and not new:
        raise HostEventError("Empty patch hunk")
    at_eof = index < len(body) and body[index] == "*** End of File"
    return old, new, index + int(at_eof), at_eof


def _apply_hunks(original: str, body: list[str]) -> str:
    """The updated file text; each hunk's context must match exactly once."""
    lines = original.splitlines()
    output: list[str] = []
    cursor = 0
    index = 0
    if body and body[0].startswith((" ", "+", "-")):
        body = ["@@", *body]
    if not body:
        raise HostEventError("Update contains no hunks")
    while index < len(body):
        anchor = body[index]
        if anchor != "@@" and not anchor.startswith("@@ "):
            raise HostEventError(f"Expected @@ patch anchor, got {anchor!r}")
        start = (
            cursor if anchor == "@@" else _match_unique(lines, [anchor[3:]], cursor) + 1
        )
        old, new, index, at_eof = _read_hunk(body, index + 1)
        position = _match_unique(lines, old, start, at_eof) if old else len(lines)
        if not old and start > position:
            raise HostEventError("Insertion outside file")
        output.extend(lines[cursor:position])
        output.extend(new)
        cursor = position + len(old)
    output.extend(lines[cursor:])
    return "\n".join(output) + ("\n" if output else "")


def _refuse_if_exists(path: str, state: dict) -> None:
    exists = state[path] is not None if path in state else Path(path).exists()
    if exists:
        raise HostEventError(f"Patch destination already exists: {path}")


def _update_operation(
    event: dict, path: str, body: list[str], state: dict, cwd: str
) -> list[dict]:
    old = _read_preimage(path, state)
    destination = path
    if body and body[0].startswith(_MOVE_PREFIX):
        destination = _resolve(body[0][len(_MOVE_PREFIX) :], cwd)
        body = body[1:]
        if destination != path:
            _refuse_if_exists(destination, state)
    new = _apply_hunks(old, body)
    state[destination] = new
    if destination != path:
        state[path] = None
        return [
            _shaped(event, "Edit", path, old_string=old, new_string=""),
            _shaped(event, "Write", destination, content=new),
        ]
    return [_shaped(event, "Edit", path, old_string=old, new_string=new)]


def _operation(event: dict, header: str, body: list[str], state: dict) -> list[dict]:
    cwd = event.get("cwd") or str(Path.cwd())
    kind, separator, raw_path = header.removeprefix("*** ").partition(": ")
    if not separator or kind not in {_ADD, _DELETE, _UPDATE}:
        raise HostEventError(f"Unsupported patch operation: {header!r}")
    path = _resolve(raw_path, cwd)
    if kind == _ADD:
        _refuse_if_exists(path, state)
        if any(not line.startswith("+") for line in body):
            raise HostEventError("Add File accepts only + lines")
        content = "".join(line[1:] + "\n" for line in body)
        state[path] = content
        return [_shaped(event, "Write", path, content=content)]
    if kind == _DELETE:
        old = _read_preimage(path, state)
        if body:
            raise HostEventError("Delete File cannot contain hunks")
        state[path] = None
        return [_shaped(event, "Edit", path, old_string=old, new_string="")]
    return _update_operation(event, path, body, state, cwd)


def patch_events(event: dict) -> list[dict]:
    """Edit/Write-shaped events derived from ``event``'s apply_patch command.

    Precondition: ``event["tool_input"]["command"]`` is the full patch text
    between (and including) ``*** Begin Patch`` / ``*** End Patch``.
    Postcondition: one event per file operation, in patch order; a later
    operation sees the prospective state (content, existence) left by an
    earlier one in the same patch, never the on-disk state. Raises
    ``HostEventError`` and produces no events on any operation whose
    preimage is missing, ambiguous, or otherwise unsafe to translate.
    """
    tool_input = event.get("tool_input")
    if not isinstance(tool_input, dict):
        raise HostEventError("apply_patch tool_input must be an object")
    command = tool_input.get("command")
    if not isinstance(command, str):
        raise HostEventError("apply_patch tool_input.command must be a string")
    lines = command.splitlines()
    if (
        len(lines) < _MIN_ENVELOPE_LINES
        or lines[0] != "*** Begin Patch"
        or lines[-1] != "*** End Patch"
    ):
        raise HostEventError("Invalid Begin Patch / End Patch envelope")
    result: list[dict] = []
    state: dict[str, str | None] = {}
    index = 1
    while index < len(lines) - 1:
        header = lines[index]
        index += 1
        body: list[str] = []
        while index < len(lines) - 1:
            line = lines[index]
            if line.startswith((f"*** {_ADD}:", f"*** {_DELETE}:", f"*** {_UPDATE}:")):
                break
            body.append(line)
            index += 1
        result.extend(_operation(event, header, body, state))
    return result
