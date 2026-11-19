"""Only stdlib subprocesses and temporary socket trees; never inference."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from mcp_server.infrastructure.capture_client import deliver
from mcp_server.infrastructure.capture_transport import Limits

WORKER = r"""
import json, os, socket, sys, time
from pathlib import Path
from mcp_server.infrastructure.capture_server import CaptureServer, ServerPolicy
from mcp_server.infrastructure.capture_socket import remove_socket
from mcp_server.infrastructure.capture_spool import spool_directory
from mcp_server.infrastructure.capture_transport import Limits
root = Path(sys.argv[3])
listener = socket.socket(fileno=int(sys.argv[1]))
async def callback(payload):
    time.sleep(payload.get("delay", 0))  # Simulate synchronous cold model loading.
    # A crash payload kills the first worker that stores it; "always" kills each one.
    first = not (root / "crashed").exists()
    if payload.get("crash") and (payload.get("always") or first):
        (root / "crashed").touch()
        os._exit(1)
    if payload.get("error"):
        raise ValueError("fixture callback failure")
    with (root / "received.jsonl").open("a") as stream:
        stream.write(json.dumps({"pid": os.getpid(), "payload": payload}) + "\n")
def report(message, elapsed, operation):
    with (root / "errors.txt").open("a") as stream:
        stream.write(f"{operation} {elapsed}: {message}\n")
limits = Limits(int(sys.argv[4]), float(sys.argv[5]), float(sys.argv[6]))
policy = ServerPolicy(limits, report, spool_directory(root))
try:
    CaptureServer(listener, callback, policy).run()
finally:
    remove_socket(root / ".capture-worker" / "socket")
    os.close(int(sys.argv[2]))
"""


class WorkerFixture(unittest.TestCase):
    def setUp(self):
        if sys.platform not in {"darwin", "linux"}:
            self.skipTest("capture worker explicitly requires Unix peer credentials")
        # Keep pathname below macOS sockaddr_un capacity; /tmp itself is a symlink.
        self.temporary = tempfile.TemporaryDirectory(
            prefix="cw-", dir=Path("/tmp").resolve()
        )
        self.root = Path(self.temporary.name)
        self.children: list[subprocess.Popen] = []
        # Fixture-only short waits; production budgets are independently pinned.
        self.limits = Limits(max_bytes=4096, timeout=2.0, idle=0.1)

    def tearDown(self):
        for child in self.children:
            if child.poll() is None:
                child.terminate()
            child.wait(timeout=5)
        self.temporary.cleanup()

    def spawn(self, listener, lease):
        arguments = [
            sys.executable,
            "-c",
            WORKER,
            str(listener.fileno()),
            str(lease),
            str(self.root),
            str(self.limits.max_bytes),
            str(self.limits.timeout),
            str(self.limits.idle),
        ]
        environment = dict(os.environ, CORTEX_CLAUDE_DIR=str(self.root))
        self.children.append(
            subprocess.Popen(
                arguments,
                pass_fds=(listener.fileno(), lease),
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        )

    def send(self, payload):
        deliver(self.root, payload, self.limits, self.spawn)

    def finish(self):
        for child in self.children:
            self.assertEqual(child.wait(timeout=5), 0)
        path = self.root / "received.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()]
