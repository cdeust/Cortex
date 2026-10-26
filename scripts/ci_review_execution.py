#!/usr/bin/env python3
"""Reject incomplete Claude action executions without exposing transcript content.

Source: anthropics/claude-code-action@aa8a7738e48bf30a40ee499ce818bef081c5ab5e,
base-action/src/{execution-file,run-claude-sdk}.ts: execution_file is a raw SDK
message array; a successful result can still contain permission_denials.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ToolBlock = dict[str, Any]
PendingTools = dict[str, str]


class ExecutionError(ValueError):
    """The recorded execution cannot prove an unblocked completion."""


def _messages(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ExecutionError("message stream must be an array")
    for message in value:
        if (
            not isinstance(message, dict)
            or not isinstance(message.get("type"), str)
            or not message.get("type")
        ):
            raise ExecutionError("message must have a string type")
    return value


def _terminal(messages: list[dict[str, Any]]) -> None:
    results = [message for message in messages if message["type"] == "result"]
    if len(results) != 1 or messages[-1] is not results[0]:
        raise ExecutionError("result must occur exactly once at the end")
    result = results[0]
    if result.get("subtype") != "success" or result.get("is_error") is not False:
        raise ExecutionError("result must report successful completion")
    denials = result.get("permission_denials")
    if not isinstance(denials, list) or denials:
        raise ExecutionError("permission denials must be explicitly empty")


def _blocks(message: dict[str, Any]) -> list[dict[str, Any]]:
    if message["type"] not in {"assistant", "user"}:
        return []
    body = message.get("message")
    if not isinstance(body, dict):
        raise ExecutionError("message body must be an object")
    content = body.get("content")
    if isinstance(content, str):
        return []
    if not isinstance(content, list) or any(
        not isinstance(block, dict)
        or not isinstance(block.get("type"), str)
        or not block.get("type")
        for block in content
    ):
        raise ExecutionError("message content must be text or content blocks")
    return content


def _tool_call(block: dict[str, Any], seen: set[str]) -> tuple[str, str]:
    identity, name, arguments = block.get("id"), block.get("name"), block.get("input")
    if (
        not isinstance(identity, str)
        or not identity
        or not isinstance(name, str)
        or not name
    ):
        raise ExecutionError("message tool call requires an identity and name")
    if not isinstance(arguments, dict):
        raise ExecutionError("message tool input must be an object")
    if identity in seen:
        raise ExecutionError("tool call identity was reused")
    if name in {"Agent", "Task"} and arguments.get("run_in_background"):
        raise ExecutionError("agent background launch cannot prove completion")
    seen.add(identity)
    return identity, name


def _tool_result(block: ToolBlock, pending: PendingTools, output: Any) -> bool:
    identity = block.get("tool_use_id")
    if not isinstance(identity, str) or identity not in pending:
        raise ExecutionError("tool result has no pending call")
    if block.get("is_error", False) is not False:
        raise ExecutionError("tool result reports an error or invalid error flag")
    if not isinstance(block.get("content"), (str, list)):
        raise ExecutionError("tool result is missing completion output")
    is_agent = pending[identity] in {"Agent", "Task"}
    # Source: https://code.claude.com/docs/en/agent-sdk/subagents#choose-whether-claude-waits-for-subagents
    # AgentOutput acknowledges background launches before their reports exist.
    if is_agent and (
        not isinstance(output, dict) or output.get("status") != "completed"
    ):
        raise ExecutionError("agent result must report structured completed status")
    pending.pop(identity)
    return is_agent


def _unambiguous_output(blocks: list[ToolBlock], pending: PendingTools) -> None:
    # Source: sdk.d.ts SDKUserMessage.tool_use_result (SDK 0.3.307): one
    # structured Output per message, keyed by the matching tool_use block. Several
    # results sharing it could let one completed status vouch for a launch ack.
    results = [block for block in blocks if block.get("type") == "tool_result"]
    # Non-string identities are left for _tool_result to reject by category.
    if len(results) > 1 and any(
        isinstance(block.get("tool_use_id"), str)
        and pending.get(block["tool_use_id"]) in {"Agent", "Task"}
        for block in results
    ):
        raise ExecutionError("agent result shares a message with other tool results")


def validate_execution(value: Any, *, require_agents: bool = False) -> None:
    """Check completion evidence, without claiming semantic review correctness."""
    messages = _messages(value)
    _terminal(messages)
    seen: set[str] = set()
    pending: dict[str, str] = {}
    completed_agent = False
    for message in messages:
        if (
            message["type"] == "system"
            and message.get("subtype") == "permission_denied"
        ):
            raise ExecutionError("permission denied event prevents completion")
        blocks = _blocks(message)
        _unambiguous_output(blocks, pending)
        for block in blocks:
            if block.get("type") == "tool_use":
                identity, name = _tool_call(block, seen)
                pending[identity] = name
            elif block.get("type") == "tool_result":
                completed_agent = (
                    _tool_result(block, pending, message.get("tool_use_result"))
                    or completed_agent
                )
    if pending:
        raise ExecutionError("tool calls remain incomplete")
    if require_agents and not completed_agent:
        raise ExecutionError("agent completion evidence is missing")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("execution_file", type=Path)
    parser.add_argument("--require-agents", action="store_true")
    args = parser.parse_args(argv)
    try:
        value = json.loads(args.execution_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeError):
        print("review execution: cannot read execution file", file=sys.stderr)
        return 1
    except (json.JSONDecodeError, RecursionError):
        print("review execution: invalid JSON execution file", file=sys.stderr)
        return 1
    try:
        validate_execution(value, require_agents=args.require_agents)
    except ExecutionError as exc:
        print(f"review execution: {exc}", file=sys.stderr)
        return 1
    print("review execution verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
