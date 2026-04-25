#!/usr/bin/env python3
# memory-mcp-server.py — MCP stdio server exposing the memory_20250818 tool schema.
#
# Late-binding principle: the tool surface is `memory_20250818`; the backend is
# swappable. If memory-tool.sh is later replaced with a Rust daemon or a remote
# API, this file's JSON schema does NOT change — only the BACKEND_CMD below and
# the argument-mapping function need updating. The abstraction barrier is here,
# between the tool schema (Anthropic-defined, stable) and the implementation
# (local, evolvable). Agents call `memory`; they do not know bash exists.
#
# Transport: JSON-RPC 2.0 over stdio, newline-delimited (one JSON object per line).
# Anthropic MCP stdio spec uses Content-Length framing for some versions; this
# server uses newline-delimited because Claude Code's MCP host sends newline-
# delimited messages and does not require Content-Length on the stdio transport.
#
# Env consumed:
#   MEMORY_AGENT_ID   — forwarded verbatim to the backend subprocess.
#   MEMORY_ROOT       — forwarded if set (allows test isolation).
#   MEMORY_NO_AUDIT   — forwarded if set.
#   MEMORY_NO_ACL     — forwarded if set.
#   MEMORY_NO_SYNC    — forwarded if set.
#
# Exit codes from backend:
#   0  → success; stdout is the tool_result content.
#   1  → contract error (verbatim error string on stdout per spec §4.5);
#         isError: true so the model sees the error string as tool feedback.
#   2  → fatal internal error; stderr has the message; surfaced as isError.
#
# stdlib only — no third-party dependencies.

import json
import os
import subprocess
import sys

# ── constants ────────────────────────────────────────────────────────────────

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_CMD = os.path.join(_SCRIPT_DIR, "memory-tool.sh")

SERVER_INFO = {
    "name": "memory-mcp-server",
    "version": "1.0.0",
}

PROTOCOL_VERSION = "2024-11-05"

# ── memory_20250818 tool schema (VERBATIM — do not paraphrase) ───────────────
# Source: platform.claude.com/docs/en/agents-and-tools/tool-use/memory-tool
# Parameter names, types, and descriptions are taken from the Anthropic spec
# and MUST NOT be altered — the model is trained on these exact strings.

MEMORY_TOOL = {
    "name": "memory",
    "description": (
        "Manages a persistent memory store across sessions. "
        "All paths must be under /memories. "
        "Commands: view, create, str_replace, insert, delete, rename."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "enum": ["view", "create", "str_replace", "insert", "delete", "rename"],
                "description": "The operation to perform.",
            },
            "path": {
                "type": "string",
                "description": (
                    "Absolute path starting with /memories. "
                    "Required for: view, create, str_replace, insert, delete."
                ),
            },
            "view_range": {
                "type": "array",
                "items": {"type": "integer"},
                "minItems": 2,
                "maxItems": 2,
                "description": (
                    "Optional [start_line, end_line] (1-indexed, inclusive). "
                    "Only valid with command=view on a file."
                ),
            },
            "file_text": {
                "type": "string",
                "description": "Content to write. Required for command=create.",
            },
            "old_str": {
                "type": "string",
                "description": (
                    "Exact string to find (must appear exactly once). "
                    "Required for command=str_replace."
                ),
            },
            "new_str": {
                "type": "string",
                "description": (
                    "Replacement string. Required for command=str_replace."
                ),
            },
            "insert_line": {
                "type": "integer",
                "description": (
                    "0-indexed line number before which to insert. "
                    "0 = before first line. Required for command=insert."
                ),
            },
            "insert_text": {
                "type": "string",
                "description": "Text to insert. Required for command=insert.",
            },
            "old_path": {
                "type": "string",
                "description": (
                    "Source path (must exist). Required for command=rename."
                ),
            },
            "new_path": {
                "type": "string",
                "description": (
                    "Destination path (must not exist). Required for command=rename."
                ),
            },
        },
        "required": ["command"],
    },
}

# ── memory_extensions tool (search / scopes / preamble / sync ops) ───────────
# Rationale: agents benefit from calling search (deterministic full-text grep),
# scopes (listing), preamble (system-prompt injection), and sync-status /
# drain-sync / commit-sync / release-sync without dropping back to Bash.
# These are NOT part of the Anthropic memory_20250818 schema, so they live in
# a separate tool to avoid schema pollution while still raising the abstraction
# barrier for the full backend surface.

MEMORY_EXTENSIONS_TOOL = {
    "name": "memory_extensions",
    "description": (
        "Extended memory backend operations not in the memory_20250818 schema. "
        "Commands: search, scopes, preamble, sync-status, drain-sync, "
        "commit-sync, release-sync, ttl-sweep, audit."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "enum": [
                    "search",
                    "scopes",
                    "preamble",
                    "sync-status",
                    "drain-sync",
                    "commit-sync",
                    "release-sync",
                    "ttl-sweep",
                    "audit",
                ],
                "description": "The extension operation to perform.",
            },
            "query": {
                "type": "string",
                "description": "Search query string. Required for command=search.",
            },
            "scope": {
                "type": "string",
                "description": "Scope name filter for search (optional).",
            },
            "limit": {
                "type": "integer",
                "description": "Max results (search) or max jobs (drain-sync).",
            },
            "regex": {
                "type": "boolean",
                "description": "Use extended regex for search (default: fixed-string).",
            },
            "job_id": {
                "type": "string",
                "description": "Job ID. Required for commit-sync and release-sync.",
            },
            "dry_run": {
                "type": "boolean",
                "description": "Dry-run mode for ttl-sweep.",
            },
            "since": {
                "type": "string",
                "description": "ISO-8601 timestamp for audit --since filter.",
            },
        },
        "required": ["command"],
    },
}

# ── JSON-RPC 2.0 helpers ──────────────────────────────────────────────────────

def _response(req_id, result):
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _error(req_id, code, message):
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def write_msg(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


# ── subprocess helper ────────────────────────────────────────────────────────

def _inherit_env():
    """Build subprocess env: inherit everything, ensure MEMORY_AGENT_ID is set."""
    env = os.environ.copy()
    # MEMORY_AGENT_ID is mandatory for audit attribution; fall back to 'unknown'
    # only if not set at all.
    if "MEMORY_AGENT_ID" not in env:
        env["MEMORY_AGENT_ID"] = "unknown"
    return env


def run_backend(args):
    """
    Run memory-tool.sh with the given arg list.
    Returns (stdout_text, is_error).
    Exit code 0 → is_error=False.
    Exit code 1 → is_error=True (contract error, stdout has verbatim message).
    Exit code 2+ → is_error=True (fatal; combine stdout+stderr).
    """
    try:
        result = subprocess.run(
            ["bash", BACKEND_CMD] + args,
            capture_output=True,
            text=True,
            env=_inherit_env(),
        )
    except OSError as exc:
        return f"Fatal: could not execute backend: {exc}", True

    stdout = result.stdout
    stderr = result.stderr.strip()

    if result.returncode == 0:
        return stdout, False

    # Exit 1: contract error — stdout has the verbatim spec error string.
    # Exit 2+: fatal internal error — stderr has the message.
    if result.returncode == 1:
        # stdout carries the contract-verbatim error; surface it as-is.
        return stdout if stdout else stderr, True

    # Fatal (exit 2).
    msg = stderr if stderr else stdout
    return msg or f"Backend exited with code {result.returncode}", True


# ── argument mapping: tool input → backend argv ──────────────────────────────

def _map_memory(params):
    """Map memory_20250818 tool input dict → memory-tool.sh argv list."""
    cmd = params.get("command")
    if cmd == "view":
        args = ["view", params["path"]]
        vr = params.get("view_range")
        if vr and len(vr) == 2:
            args += [str(vr[0]), str(vr[1])]
        return args

    if cmd == "create":
        return ["create", params["path"], params.get("file_text", "")]

    if cmd == "str_replace":
        return [
            "str_replace",
            params["path"],
            params.get("old_str", ""),
            params.get("new_str", ""),
        ]

    if cmd == "insert":
        return [
            "insert",
            params["path"],
            str(params.get("insert_line", 0)),
            params.get("insert_text", ""),
        ]

    if cmd == "delete":
        return ["delete", params["path"]]

    if cmd == "rename":
        return ["rename", params["old_path"], params["new_path"]]

    return None  # unknown command — caller handles


def _map_extensions(params):
    """Map memory_extensions tool input dict → memory-tool.sh argv list."""
    cmd = params.get("command")

    if cmd == "search":
        args = ["search", params.get("query", "")]
        if params.get("scope"):
            args += ["--scope", params["scope"]]
        if params.get("limit"):
            args += ["--limit", str(params["limit"])]
        if params.get("regex"):
            args += ["--regex"]
        return args

    if cmd == "scopes":
        return ["scopes"]

    if cmd == "preamble":
        return ["preamble"]

    if cmd == "sync-status":
        return ["sync-status"]

    if cmd == "drain-sync":
        args = ["drain-sync"]
        if params.get("limit"):
            args += ["--limit", str(params["limit"])]
        return args

    if cmd == "commit-sync":
        return ["commit-sync", params.get("job_id", "")]

    if cmd == "release-sync":
        return ["release-sync", params.get("job_id", "")]

    if cmd == "ttl-sweep":
        args = ["ttl-sweep"]
        if params.get("dry_run"):
            args += ["--dry-run"]
        return args

    if cmd == "audit":
        args = ["audit"]
        if params.get("since"):
            args += ["--since", params["since"]]
        return args

    return None


# ── tool_result builder ──────────────────────────────────────────────────────

def _tool_result(text, is_error):
    result = {
        "content": [{"type": "text", "text": text}],
    }
    if is_error:
        result["isError"] = True
    return result


# ── MCP method handlers ───────────────────────────────────────────────────────

def handle_initialize(req_id, params):
    return _response(req_id, {
        "protocolVersion": PROTOCOL_VERSION,
        "serverInfo": SERVER_INFO,
        "capabilities": {"tools": {}},
    })


def handle_tools_list(req_id, params):
    return _response(req_id, {
        "tools": [MEMORY_TOOL, MEMORY_EXTENSIONS_TOOL],
    })


def handle_tools_call(req_id, params):
    tool_name = params.get("name", "")
    tool_input = params.get("arguments") or params.get("input") or {}

    if tool_name == "memory":
        args = _map_memory(tool_input)
        if args is None:
            return _response(req_id, _tool_result(
                f"Error: unknown command '{tool_input.get('command')}'", True
            ))
        text, is_error = run_backend(args)
        return _response(req_id, _tool_result(text, is_error))

    if tool_name == "memory_extensions":
        args = _map_extensions(tool_input)
        if args is None:
            return _response(req_id, _tool_result(
                f"Error: unknown extension command '{tool_input.get('command')}'", True
            ))
        text, is_error = run_backend(args)
        return _response(req_id, _tool_result(text, is_error))

    return _error(req_id, -32601, f"Tool not found: {tool_name}")


# ── dispatch table ───────────────────────────────────────────────────────────

_HANDLERS = {
    "initialize": handle_initialize,
    "tools/list": handle_tools_list,
    "tools/call": handle_tools_call,
}


# ── main loop ─────────────────────────────────────────────────────────────────

def main():
    for raw_line in sys.stdin:
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            req = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            write_msg(_error(None, -32700, f"Parse error: {exc}"))
            continue

        req_id = req.get("id")
        method = req.get("method", "")
        params = req.get("params") or {}

        handler = _HANDLERS.get(method)
        if handler is None:
            # Notifications (no id) are silently dropped per JSON-RPC spec.
            if req_id is not None:
                write_msg(_error(req_id, -32601, f"Method not found: {method}"))
            continue

        try:
            resp = handler(req_id, params)
            write_msg(resp)
        except Exception as exc:  # noqa: BLE001
            write_msg(_error(req_id, -32603, f"Internal error: {exc}"))


if __name__ == "__main__":
    main()
