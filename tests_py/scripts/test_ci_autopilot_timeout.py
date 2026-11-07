"""Bound an owned helper session without killing another process session."""

import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import ci_autopilot_review as helper
from tests_py.scripts import test_ci_autopilot_helper_failures as failure_fixtures


def process_fixture(root, budget):
    # Controlled fixture outlives its configured budget; no network or models.
    duration = budget + budget
    script, pidfile = root / "helper.py", root / "pids.json"
    script.write_text(
        "import os,json,subprocess,sys,time;from pathlib import Path\n"
        f"command='import time;time.sleep({duration})'\n"
        "g=subprocess.Popen([sys.executable,'-c',command])\n"
        "pids=dict(leader=os.getpid(),group=os.getpgrp(),descendant=g.pid)\n"
        f"Path({str(pidfile)!r}).write_text(json.dumps(pids))\n"
        f"time.sleep({duration});print(json.dumps(dict(action='none')))\n"
    )
    sentinel = subprocess.Popen(
        [sys.executable, "-c", f"import time;time.sleep({duration})"],
        start_new_session=True,
    )
    return script, pidfile, sentinel


@unittest.skipUnless(hasattr(os, "killpg"), "the launchd service is POSIX-only")
class OwnedTimeout(unittest.TestCase):
    def assert_group_stopped(self, pidfile, sentinel):
        ids = json.loads(pidfile.read_text())
        self.assertEqual(ids["leader"], ids["group"])
        self.assertNotEqual(ids["group"], os.getpgrp())
        state = subprocess.run(
            ["ps", "-p", str(ids["descendant"]), "-o", "stat="],
            capture_output=True,
            text=True,
        )
        self.assertIn(state.stdout.strip(), ("", "Z"))
        self.assertIsNone(sentinel.poll())

    def test_timeout_kills_owned_descendant_and_preserves_other_session(self):
        # source: controlled fixture lives for twice its configured one-second budget.
        options = SimpleNamespace(
            repository="cdeust/Cortex", repo=Path.cwd(), interval=1
        )
        with tempfile.TemporaryDirectory() as directory:
            root, diagnostic = Path(directory), io.StringIO()
            script, pidfile, sentinel = process_fixture(root, options.interval)
            try:
                with (
                    patch.object(helper, "__file__", str(script)),
                    patch("sys.stderr", diagnostic),
                ):
                    result = helper.reconcile(options, {"number": 12, "sha": "a" * 40})
                self.assertEqual(
                    result,
                    {
                        "action": "none",
                        "reason": "helper_failure",
                        "category": "environment",
                        "timeout_seconds": 1,
                    },
                )
                self.assert_group_stopped(pidfile, sentinel)
            finally:
                sentinel.kill()
                sentinel.wait()


class TimeoutQueue(unittest.TestCase):
    inputs = failure_fixtures.HelperFailures.inputs

    def test_timeout_preserves_settlement_and_later_work(self):
        failure_fixtures.HelperFailures.queue(
            self, subprocess.TimeoutExpired(["controlled-helper"], 1)
        )
