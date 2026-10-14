"""Drive the plugin's MCP server over stdio the way Claude Code starts it.

The command, arguments and environment are read from the installed
``plugin.json`` and substituted as the host substitutes them, so the server
runs exactly as a first session runs it: ``python3`` from the machine's PATH,
``${CLAUDE_PLUGIN_ROOT}`` and ``${user_config.database_url}`` (empty when the
user configured nothing). Then: initialize, tools/list, remember a unique
token, recall it.

source: scripts/locked_mac_env/session_e2e.py on feat/744-pg0-launcher
(commit cb06c405), adapted to read the manifest instead of restating it.
"""

from __future__ import annotations

import json
import subprocess
import uuid
from pathlib import Path
from typing import IO

PROTOCOL_VERSION = "2025-06-18"  # source: scripts/mcp_host_client.py PROTOCOL_VERSION
REQUIRED_TOOLS = ("remember", "recall")  # source: the owner's acceptance, brief step 0


def server_command(root: Path, data: Path, base_env: dict) -> tuple[list, dict]:
    """``mcpServers.cortex`` from the installed manifest, substituted."""
    manifest = json.loads((root / ".claude-plugin" / "plugin.json").read_text())
    server = manifest["mcpServers"]["cortex"]
    values = {
        "${CLAUDE_PLUGIN_ROOT}": str(root),
        "${CLAUDE_PLUGIN_DATA}": str(data),
        "${user_config.database_url}": "",
    }

    def substitute(text: str) -> str:
        for token, value in values.items():
            text = text.replace(token, value)
        return text

    argv = [substitute(server["command"])] + [substitute(a) for a in server["args"]]
    env = dict(base_env)
    env.update(CLAUDE_PLUGIN_ROOT=str(root), CLAUDE_PLUGIN_DATA=str(data))
    env.update({k: substitute(v) for k, v in server.get("env", {}).items()})
    return argv, env


def _send(stdin: IO[str], message: dict) -> None:
    stdin.write(json.dumps(message) + "\n")
    stdin.flush()


def _reply(stdout: IO[str], request_id: int) -> dict:
    for line in stdout:
        line = line.strip()
        if line.startswith("{"):
            message = json.loads(line)
            if message.get("id") == request_id:
                return message
    raise RuntimeError(f"server closed stdout before answering request {request_id}")


def _request(proc: subprocess.Popen, request_id: int, method: str, params: dict) -> dict:
    assert proc.stdin is not None and proc.stdout is not None
    _send(
        proc.stdin,
        {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params},
    )
    return _reply(proc.stdout, request_id)


def _text(response: dict) -> str:
    parts = (response.get("result") or {}).get("content") or []
    return "\n".join(str(p.get("text", "")) for p in parts) or json.dumps(response)


def _converse(proc: subprocess.Popen, token: str, project: Path) -> dict:
    init = _request(
        proc,
        1,
        "initialize",
        {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "install-e2e", "version": "1"},
        },
    )
    assert proc.stdin is not None
    _send(proc.stdin, {"jsonrpc": "2.0", "method": "notifications/initialized"})
    tools = _request(proc, 2, "tools/list", {})
    names = [t.get("name") for t in (tools.get("result") or {}).get("tools", [])]
    content = f"The zero-ops install check stored the marker {token} on first launch."
    stored = _request(
        proc,
        3,
        "tools/call",
        {"name": "remember", "arguments": {"content": content, "force": True, "directory": str(project)}},
    )
    found = _request(
        proc,
        4,
        "tools/call",
        {"name": "recall", "arguments": {"query": f"zero-ops install marker {token}", "min_heat": 0}},
    )
    return {"init": init, "names": names, "stored": stored, "found": found}


def remember_recall(argv: list, env: dict, project: Path, log: Path) -> dict:
    """Start the server, run the conversation, stop it; report what happened."""
    token = f"zero-ops-{uuid.uuid4().hex[:12]}"
    with log.open("a") as errors:
        proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=errors,
            env=env,
            cwd=project,
            text=True,
        )
        try:
            talk = _converse(proc, token, project)
        finally:
            assert proc.stdin is not None
            proc.stdin.close()
            proc.wait(timeout=60)
    recalled = _text(talk["found"])
    return {
        "initialize_ok": "result" in talk["init"],
        "tools_listed": len(talk["names"]),
        "required_tools_present": all(n in talk["names"] for n in REQUIRED_TOOLS),
        "remember": _text(talk["stored"])[:400],
        "recall_contains_token": token in recalled,
        "recall_excerpt": recalled[:400],
        "server_returncode": proc.returncode,
    }
