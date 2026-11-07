"""A failed helper is visible per PR and cannot discard settled queue state."""

import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import ci_autopilot as runtime
import ci_autopilot_review as helper


class HelperFailures(unittest.TestCase):
    def inputs(self):
        wait = {
            "kind": "review_resume",
            "number": 12,
            "sha": "a" * 40,
            "fingerprint": "wait",
        }
        issue = {"kind": "issue", "number": 13, "fingerprint": "approved"}
        state = {
            "run": "run_fixture",
            "seen": {},
            "active": {
                "kind": "pull",
                "number": 11,
                "fingerprint": "settled",
                "dispatch": "ctx_fixture",
            },
        }
        worker = {
            "dispatchId": "ctx_fixture",
            "terminalState": "retained",
            "dispatchStatus": "completed",
        }
        options = SimpleNamespace(
            inspect=False, repository="cdeust/Cortex", repo=Path.cwd()
        )
        return options, state, [wait, issue], [worker]

    def queue(self, process):
        options, state, items, workers = self.inputs()
        diagnostic = io.StringIO()
        with (
            patch.object(runtime, "snapshot", return_value=items),
            patch.object(runtime, "workers", return_value=workers),
            patch.object(helper, "invoke_child", side_effect=process),
            patch.object(
                runtime, "launch", return_value={"state": "started"}
            ) as launch,
            patch("sys.stderr", diagnostic),
        ):
            self.assertEqual(runtime.tick(options, state), {"state": "started"})
        self.assertEqual(launch.call_args.args[-1]["number"], 13)
        self.assertNotIn("active", state)
        self.assertEqual(state["seen"], {"pull:11": "settled"})
        self.assertIn("helper_failure", diagnostic.getvalue())
        self.assertNotIn("private-token-value", diagnostic.getvalue())

    def test_child_exit_and_spawn_errors_preserve_settlement_and_later_work(self):
        def failed(*args, **kwargs):
            done = subprocess.CompletedProcess([], 1, "", "private-token-value")
            if kwargs.get("check"):
                raise subprocess.CalledProcessError(1, [], stderr=done.stderr)
            return done

        self.queue(failed)
        self.queue(FileNotFoundError("private-token-value"))

    def test_invalid_json_or_contract_preserves_later_work(self):
        for output in (
            "",
            "{",
            "null",
            json.dumps({"action": "merge"}),
            json.dumps(
                {
                    "action": "repair",
                    "reason": "evidence_unverifiable",
                    "category": "protocol",
                }
            ),
            json.dumps({"action": "none", "reason": "review_infrastructure"}),
            json.dumps(
                {
                    "action": "none",
                    "reason": "evidence_unverifiable",
                    "category": "private-token-value",
                }
            ),
        ):

            def process(*args, output=output, **kwargs):
                return subprocess.CompletedProcess([], 0, output, "private-token-value")

            with self.subTest(output=output):
                self.queue(process)

    def test_real_crashing_python_child_has_fixed_visible_diagnostic(self):
        options = SimpleNamespace(repository="cdeust/Cortex", repo=Path.cwd())
        diagnostic = io.StringIO()
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "failed-helper.py"
            script.write_text("raise TypeError('private-token-value')\n")
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
                "exit_code": 1,
            },
        )
        self.assertIn("exit_code=1", diagnostic.getvalue())
        self.assertNotIn("private-token-value", diagnostic.getvalue())
