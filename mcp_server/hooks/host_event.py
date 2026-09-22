"""Normalize a Codex hook event into the Claude-shaped events the lifecycle
hooks already read.

Fields shared by both hosts (``session_id``, ``transcript_path``, ``cwd``,
``hook_event_name``, ``tool_name``, ``tool_input``, ``tool_response``, and
the per-event fields ``source``, ``reason``, ``trigger``, ``prompt``) are
verified against learn.chatgpt.com/docs/hooks (read 2026-09-17) and the same
owner's zetetic-team-subagents ``hooks/lib/host_events.py`` and
``hooks/lib/gate_targets.py``, which run live under Codex. A Claude Code
event already matches the shape every hook module reads, so it passes
through unchanged; only the Codex-specific shapes below are translated.
"""

from __future__ import annotations

import os
from pathlib import Path

from mcp_server.hooks.host_event_errors import HostEventError
from mcp_server.hooks.host_patch import patch_events

__all__ = ["HostEventError", "normalize_event"]

_SHELL_TOOLS = {"exec_command", "shell_command"}


def _shell_event(event: dict, tool_name: str) -> dict:
    """A Bash-shaped event; ``workdir`` (or ``tool_input.cwd`` when no
    ``workdir`` key is present -- the same fallback order
    zetetic-team-subagents' ``host_events.py`` uses) resolves against the
    event's own ``cwd``."""
    tool_input = event.get("tool_input")
    if not isinstance(tool_input, dict):
        raise HostEventError(f"{tool_name} tool_input must be an object")
    command = tool_input.get("cmd", tool_input.get("command"))
    if not isinstance(command, str):
        raise HostEventError("Shell command must be a string")
    base = event.get("cwd") or os.getcwd()
    workdir = tool_input.get("workdir") or tool_input.get("cwd")
    cwd = str((Path(base) / workdir).resolve()) if workdir else base
    return {
        **event,
        "tool_name": "Bash",
        "cwd": cwd,
        "tool_input": {**tool_input, "command": command},
    }


def _subagent_start_event(event: dict) -> dict:
    """Keep native role identity; promptless starts receive project context.

    Task context is added independently at PreToolUse from exact spawn arguments.
    source: ADR-1085
    """
    mapped = dict(event)
    agent_type = event.get("agent_type")
    if agent_type is not None:
        mapped["agent_name"] = agent_type
    return mapped


def normalize_event(event: dict) -> list[dict]:
    """Ordered Claude-shaped hook events derived from one host event.

    Precondition: ``event`` is the JSON object a hook receives on stdin,
    from either host. Postcondition: for a Claude Code event, returns
    ``[event]`` unchanged (byte-identical once re-serialized). For a Codex
    event, returns the equivalent Claude-shaped event(s): ``apply_patch``
    expands to one Edit/Write event per file operation (see
    ``host_patch.patch_events``); ``exec_command``/``shell_command`` become
    one ``Bash`` event; ``SubagentStart`` maps ``agent_type`` to
    ``agent_name``. Any other event, including ``PreCompact``/``PostCompact``
    (which the compaction module reads with no field checks, the same way
    it reads a Claude ``Notification: compacted`` event) and unknown tools,
    passes through unchanged. Raises ``HostEventError`` on a shape that
    cannot be normalized without losing edit information; never mutates
    ``event`` or any file on disk.
    """
    if not isinstance(event, dict):
        raise HostEventError("Hook event must be an object")
    if event.get("hook_event_name") == "SubagentStart":
        return [_subagent_start_event(event)]
    tool_name = event.get("tool_name")
    if tool_name == "apply_patch":
        return patch_events(event)
    if tool_name in _SHELL_TOOLS:
        return [_shell_event(event, tool_name)]
    return [event]
