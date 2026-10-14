"""First-launch MCP stand-in: answer the host now, hand over when installed.

Claude Code gives a stdio server 30 s to answer ``initialize`` and never
reconnects one that misses it. A first launch needs longer: the pinned uv,
possibly a Python, and the base dependency set (measured 58 s cold on
2026-10-14). So when the runtime is not installed yet, the launcher runs this
stand-in instead of the server. Stdlib only, Python 3.9 safe.

* It answers ``initialize`` at once with the real server's identity and
  capabilities (``listChanged`` on, since the lists will change), an empty
  tool list, and a "still installing" error for any other request.
* A worker starts the real server as a child (``launcher.py mcp_server`` with
  ``CORTEX_MCP_DIRECT=1``: the child installs what is missing, then serves),
  initializes it with the host's own parameters, then tells the host its
  tools, prompts and resources changed, and from then on copies every line
  both ways unchanged.
* ``server/discover`` (the stateless protocol probe) gets "method not found",
  so the host uses the ``initialize`` handshake this stand-in can answer.

source: docs/adr/ADR-1104-zero-ops-plugin-install.md
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading

import launcher_mcp_wire as _wire

DIRECT_ENV = (
    "CORTEX_MCP_DIRECT"  # source: ADR-1104 (the child serves; never a second stand-in)
)
_CHILD_INIT_ID = (
    "cortex-bootstrap-initialize"  # source: ADR-1104 (cannot collide with host ids)
)


class StandIn:
    """The stand-in's state: one host, at most one child, one write lock."""

    def __init__(self, child_argv: list, host_out) -> None:
        self.child_argv = child_argv
        self.host_out = host_out
        self.write_lock = threading.Lock()
        self.child: subprocess.Popen | None = None
        self.forwarding = threading.Event()
        self.handing_over: threading.Thread | None = None
        self.child_started = threading.Event()
        self.agreed_version = ""
        self.init_params: dict = {}

    def to_host(self, message: dict) -> None:
        self.write_line(json.dumps(message))

    def write_line(self, line: str) -> None:
        with self.write_lock:
            self.host_out.write(line.rstrip("\n") + "\n")
            self.host_out.flush()

    def handle(self, line: str) -> None:
        """One line from the host: forward it, or answer it here."""
        if self.forwarding.is_set():
            assert self.child is not None and self.child.stdin is not None
            self.child.stdin.write(line)
            self.child.stdin.flush()
            return
        message = _wire.parse(line)
        if message is None or "id" not in message or "method" not in message:
            return  # a notification before hand-over has no one to reach
        if message["method"] == "initialize":
            self.init_params = dict(message.get("params") or {})
            self.agreed_version = _wire.agreed_version(self.init_params)
            self.to_host(_wire.initialize_result(message["id"], self.agreed_version))
            self.handing_over = threading.Thread(target=self.hand_over, daemon=True)
            self.handing_over.start()
            return
        self.to_host(_wire.local_answer(message))

    def hand_over(self) -> None:
        """Start the real server, initialize it, then forward both ways."""
        env = dict(os.environ)
        env[DIRECT_ENV] = "1"
        self.child = subprocess.Popen(
            self.child_argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            env=env,
            text=True,
            encoding="utf-8",
        )
        self.child_started.set()
        try:
            self._initialize_child()
        except _wire.HandOverError as exc:
            print(f"[cortex-launcher] MCP hand-over failed: {exc}", file=sys.stderr)
            self.child.kill()
            return
        self.forwarding.set()
        threading.Thread(target=self._copy_child_output, daemon=True).start()
        for kind in ("tools", "prompts", "resources"):
            self.to_host(
                {"jsonrpc": "2.0", "method": f"notifications/{kind}/list_changed"}
            )

    def _initialize_child(self) -> None:
        assert self.child is not None and self.child.stdin is not None
        params = dict(self.init_params, protocolVersion=self.agreed_version)
        request = {
            "jsonrpc": "2.0",
            "id": _CHILD_INIT_ID,
            "method": "initialize",
            "params": params,
        }
        self.child.stdin.write(json.dumps(request) + "\n")
        self.child.stdin.flush()
        reply = _wire.await_reply(self.child, _CHILD_INIT_ID)
        _wire.check_child_initialize(reply, self.agreed_version)
        self.child.stdin.write(
            json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n"
        )
        self.child.stdin.flush()

    def _copy_child_output(self) -> None:
        assert self.child is not None and self.child.stdout is not None
        for line in self.child.stdout:
            self.write_line(line)

    def close(self) -> None:
        """Host closed stdin: close the child's, let it exit, then stop it."""
        if self.handing_over is not None:
            self.child_started.wait(_wire.CHILD_EXIT_SECONDS)
        if self.child is None:
            return
        if self.child.stdin is not None:
            self.child.stdin.close()
        try:
            self.child.wait(timeout=_wire.CHILD_EXIT_SECONDS)
        except subprocess.TimeoutExpired:
            self.child.terminate()
            self.child.wait()


def serve(child_argv: list) -> None:
    """Run the stand-in on this process's stdio until the host closes stdin."""
    stand_in = StandIn(child_argv, sys.stdout)
    try:
        # JSON-RPC is UTF-8 on the wire; the text stream would decode with the
        # locale's code page (issue #664).
        for raw in sys.stdin.buffer:
            stand_in.handle(raw.decode("utf-8"))
    finally:
        stand_in.close()
