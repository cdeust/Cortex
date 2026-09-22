"""Correlate completed shell reads with their own asynchronous process.

source: ADR-1086
exec_command/write_stdin exit_code and session_id contract.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from mcp_server.hooks.shell_read_paths import shell_read_paths


def _response(event: dict[str, Any]) -> dict[str, Any]:
    response = event.get("tool_response")
    # Native Bash supplies stdout alone, including JSON-shaped stdout. Never
    # treat command-controlled output as the host's execution metadata.
    return response if isinstance(response, dict) else {}


def _pending_path(root: Path, event: dict[str, Any], process: object) -> Path | None:
    session = event.get("session_id")
    if not isinstance(session, str) or not session or isinstance(process, bool):
        return None
    if not isinstance(process, (str, int)) or str(process) == "":
        return None
    digest = hashlib.sha256(json.dumps([session, str(process)]).encode()).hexdigest()
    return root / f"{digest}.json"


def _resume(
    event: dict[str, Any], response: dict[str, Any], pending_root: Path
) -> tuple[list[str], str | None]:
    inputs = event.get("tool_input") or {}
    if not isinstance(inputs, dict):
        return [], None
    pending = _pending_path(pending_root, event, inputs.get("session_id"))
    if pending is None or not pending.is_file():
        return [], None
    if inputs.get("chars", ""):
        pending.unlink()
        return [], None
    if response.get("exit_code") is None:
        return [], None
    data = json.loads(pending.read_text())
    pending.unlink()
    if not isinstance(data, dict):
        return [], None
    if response.get("exit_code") != 0 or response.get("is_error"):
        return [], None
    paths, project = data.get("paths"), data.get("project")
    if not isinstance(paths, list) or not all(isinstance(p, str) for p in paths):
        return [], None
    return paths, project if isinstance(project, str) else None


def completed_shell_read(
    event: dict[str, Any], project: str | None, pending_root: Path
) -> tuple[list[str], str | None]:
    """Use native completed access cues or structured completion metadata.

    Native Bash emits PostToolUse at completion but omits exit status even on
    failure. Explicit existing operands are attempted access cues, not proof
    that their bytes were read (native capture 2026-09-22, ADR-1086).
    """
    response = _response(event)
    if event.get("tool_name") == "write_stdin":
        return _resume(event, response, pending_root)
    inputs = event.get("tool_input") or {}
    if not isinstance(inputs, dict):
        return [], project
    command = inputs.get("command", inputs.get("cmd"))
    cwd = event.get("cwd")
    if not isinstance(command, str) or not isinstance(cwd, str) or not cwd:
        return [], project
    workdir = inputs.get("workdir") or inputs.get("cwd")
    if isinstance(workdir, str) and event.get("tool_name") != "Bash":
        cwd = str((Path(cwd) / workdir).resolve())
    paths = shell_read_paths(command, cwd)
    if (
        event.get("tool_name") == "Bash"
        and event.get("hook_event_name") == "PostToolUse"
        and isinstance(event.get("tool_response"), str)
    ):
        return paths, project
    if response.get("exit_code") == 0 and not response.get("is_error"):
        return paths, project
    pending = _pending_path(pending_root, event, response.get("session_id"))
    if paths and pending is not None and response.get("exit_code") is None:
        pending.parent.mkdir(parents=True, exist_ok=True)
        pending.write_text(json.dumps({"paths": paths, "project": project}))
    return [], project
