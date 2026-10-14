"""scripts/launcher_mcp_bootstrap.py: the first-launch MCP stand-in.

The host gets an answer to initialize at once, an empty tool list, then
``list_changed`` and every later message forwarded to the real server. The
stand-in must describe itself as the real server does, and must run on the
Python 3.9 a Mac without a newer Python starts it with.

source: ADR-1104
"""

from __future__ import annotations

import ast
import io
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"
_FAKE_SERVER = """
import json, sys
for line in sys.stdin:
    m = json.loads(line)
    if "id" not in m:
        continue
    if m["method"] == "initialize":
        r = {"protocolVersion": m["params"]["protocolVersion"], "capabilities": {}}
    elif m["method"] == "tools/list":
        r = {"tools": [{"name": "remember"}, {"name": "recall"}]}
    else:
        r = {"echo": m["method"]}
    print(json.dumps({"jsonrpc": "2.0", "id": m["id"], "result": r}), flush=True)
"""


@pytest.fixture
def modules(monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    monkeypatch.syspath_prepend(str(REPO_ROOT))
    import launcher_mcp_bootstrap
    import launcher_mcp_wire

    return launcher_mcp_bootstrap, launcher_mcp_wire


class _Host(io.StringIO):
    """The host's end of stdout: records each message, signals arrivals."""

    def __init__(self) -> None:
        super().__init__()
        self.messages: list = []
        self.arrived = threading.Condition()

    def write(self, text: str) -> int:
        with self.arrived:
            self.messages += [json.loads(t) for t in text.splitlines() if t]
            self.arrived.notify_all()
        return len(text)

    def wait_for(self, predicate, seconds: float = 30) -> dict:
        with self.arrived:
            assert self.arrived.wait_for(
                lambda: any(predicate(m) for m in self.messages), seconds
            ), self.messages
            return next(m for m in self.messages if predicate(m))


def _request(request_id, method: str, params: dict | None = None) -> str:
    return json.dumps(
        {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}}
    )


def _initialize(version: str = "2025-11-25") -> str:
    params = {
        "protocolVersion": version,
        "capabilities": {},
        "clientInfo": {"name": "t", "version": "1"},
    }
    return _request(0, "initialize", params)


def test_answers_locally_until_the_server_is_up(modules):
    bootstrap, wire = modules
    host = _Host()
    stand_in = bootstrap.StandIn(
        [sys.executable, "-c", "import sys; sys.stdin.read()"], host
    )
    stand_in.handle(_request("probe", "server/discover"))
    stand_in.handle(_initialize())
    stand_in.handle(_request(1, "tools/list"))
    stand_in.handle(_request(2, "ping"))
    stand_in.handle(_request(3, "tools/call", {"name": "recall"}))
    by_id = {m["id"]: m for m in host.messages}
    assert by_id["probe"]["error"]["code"] == wire.METHOD_NOT_FOUND
    assert by_id[0]["result"]["capabilities"]["tools"] == {"listChanged": True}
    assert by_id[1]["result"] == {"tools": []}
    assert by_id[2]["result"] == {}
    assert by_id[3]["error"]["code"] == wire.NOT_READY_CODE
    stand_in.close()


def test_hands_over_then_forwards_both_ways(modules):
    bootstrap, _ = modules
    host = _Host()
    stand_in = bootstrap.StandIn([sys.executable, "-c", _FAKE_SERVER], host)
    stand_in.handle(_initialize("2025-06-18"))
    host.wait_for(lambda m: m.get("method") == "notifications/resources/list_changed")
    changed = [m["method"] for m in host.messages if "method" in m]
    assert changed == [
        "notifications/tools/list_changed",
        "notifications/prompts/list_changed",
        "notifications/resources/list_changed",
    ]
    stand_in.handle(_request(7, "tools/list") + "\n")
    listed = host.wait_for(lambda m: m.get("id") == 7)
    assert [t["name"] for t in listed["result"]["tools"]] == ["remember", "recall"]
    stand_in.close()
    assert stand_in.child is not None and stand_in.child.returncode == 0


def test_a_server_that_dies_before_initialize_is_reported(modules, capsys):
    bootstrap, _ = modules
    stand_in = bootstrap.StandIn([sys.executable, "-c", "raise SystemExit(3)"], _Host())
    stand_in.agreed_version = "2025-11-25"
    stand_in.hand_over()
    assert "MCP hand-over failed" in capsys.readouterr().err
    assert not stand_in.forwarding.is_set()


def test_an_unknown_protocol_revision_gets_the_newest_handshake(modules):
    _, wire = modules
    assert wire.agreed_version({"protocolVersion": "2099-01-01"}) == "2025-11-25"
    assert wire.agreed_version({"protocolVersion": "2025-03-26"}) == "2025-03-26"


def test_the_stand_in_describes_itself_as_the_real_server_does(modules, tmp_path):
    """Drift guard: run the real server and compare its initialize result."""
    _, wire = modules
    env = dict(os.environ, HOME=str(tmp_path), CORTEX_MEMORY_STORE_BACKEND="sqlite")
    real = subprocess.run(
        [sys.executable, "-m", "mcp_server"],
        input=_initialize() + "\n",
        capture_output=True,
        text=True,
        env=env,
        cwd=REPO_ROOT,
        timeout=120,
    )
    first = next(line for line in real.stdout.splitlines() if line.startswith("{"))
    actual = json.loads(first)["result"]
    ours = wire.initialize_result(0, "2025-11-25")["result"]
    assert ours["serverInfo"] == actual["serverInfo"]
    assert ours["instructions"] == actual["instructions"]
    assert ours["protocolVersion"] == actual["protocolVersion"]
    assert set(ours["capabilities"]) == set(actual["capabilities"])


@pytest.mark.parametrize(
    "name",
    ["launcher.py", "launcher_mcp_bootstrap.py", "launcher_mcp_wire.py",
     "launcher_python.py", "launcher_uv.py", "launcher_pip.py", "launcher_deps.py",
     "launcher_lock.py", "launcher_ml.py", "launcher_site.py"],
)  # fmt: skip
def test_what_runs_before_the_reexec_parses_as_python_3_9(name: str):
    """A Mac's /usr/bin/python3 is 3.9: these files run on it before re-exec."""
    ast.parse((SCRIPTS / name).read_text(encoding="utf-8"), feature_version=(3, 9))
