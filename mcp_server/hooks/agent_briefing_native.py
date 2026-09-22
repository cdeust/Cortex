"""Codex child request and response adapters. source: ADR-1085

The spawn arguments are the only task source; never read the parent transcript.
"""

from __future__ import annotations

import json
from typing import Any


def native_request(event: dict) -> tuple[str, str] | None:
    """Return native role/task, or None for legacy Claude events."""
    if event.get("hook_event_name") == "PreToolUse":
        if event.get("tool_name") not in {"spawn_agent", "Agent"}:
            return None
        arguments = event.get("tool_input")
        if not isinstance(arguments, dict):
            raise ValueError("spawn arguments must be an object")
        message = arguments.get("message")
        role = arguments.get("agent_type", "default")
        if not isinstance(message, str) or not isinstance(role, str):
            raise ValueError("spawn message and agent_type must be strings")
        return role.lower(), message
    if event.get("hook_event_name") == "SubagentStart" and "agent_type" in event:
        role = event["agent_type"]
        if not isinstance(role, str):
            raise ValueError("agent_type must be a string")
        prompt = event.get("prompt") or ""
        if not isinstance(prompt, str):
            raise ValueError("agent prompt must be a string")
        return role.lower(), prompt
    return None


def emit_native(event: dict, briefing: str) -> None:
    """Keep the whole original argument object and append bounded context."""
    kind = event["hook_event_name"]
    output: dict[str, Any] = {"hookEventName": kind}
    if kind == "PreToolUse":
        arguments = event["tool_input"]
        output.update(
            permissionDecision="allow",
            updatedInput={
                **arguments,
                "message": arguments["message"]
                + "\n\n<cortex-briefing>\n"
                + briefing
                + "\n</cortex-briefing>",
            },
        )
    else:
        output["additionalContext"] = briefing
    print(json.dumps({"hookSpecificOutput": output}))
