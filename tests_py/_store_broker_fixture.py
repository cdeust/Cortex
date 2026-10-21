"""A real store broker for tests: started by the client like in production,
through a launcher that runs the broker module with this interpreter under
a short Cortex root (sockaddr_un holds about 104 bytes on macOS); every
broker started is killed at teardown.

source: ADR-1112
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from mcp_server.infrastructure import broker_endpoint

_REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def broker_env(monkeypatch):
    """Yield ``(root, children)``: the Cortex root the brokers use and the
    broker processes started so far."""
    root = Path(tempfile.mkdtemp(prefix="sb-", dir=Path("/tmp").resolve()))
    children: list[subprocess.Popen] = []

    def launcher(module, arguments, environment, fds, output):
        env = {**os.environ, **environment, "CORTEX_CLAUDE_DIR": str(root)}
        env["CORTEX_BROKER_IDLE_SECONDS"] = "2"
        children.append(
            subprocess.Popen(
                [sys.executable, "-m", module, *arguments],
                pass_fds=fds,
                start_new_session=True,
                stdin=subprocess.DEVNULL,
                stdout=output.open("wb"),
                stderr=subprocess.STDOUT,
                cwd=_REPO,
                env=env,
            )
        )

    monkeypatch.setattr(broker_endpoint, "_launcher", launcher)
    yield root, children
    for child in children:
        if child.poll() is None:
            child.kill()
        child.wait(timeout=10)
    subprocess.run(["rm", "-rf", str(root)], check=False)
