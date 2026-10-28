"""Keep legacy dispatcher CLI compatibility with an explicit operator budget."""

import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import ci_autopilot as runtime
import ci_autopilot_review as helper


class IntervalConfig(unittest.TestCase):
    def command(self, root, value=None):
        args = [
            "ci_autopilot.py",
            "--repo",
            str(root),
            "--control",
            str(root),
            "--state",
            str(root / "state.json"),
            "--brief",
            str(root / "brief.md"),
            "--inspect",
        ]
        return args if value is None else args + ["--interval", str(value)]

    def test_legacy_cli_default_and_explicit_interval_reach_dispatcher(self):
        for value in (None, 1):
            with tempfile.TemporaryDirectory() as directory:
                with (
                    patch.object(sys, "argv", self.command(Path(directory), value)),
                    patch.object(
                        runtime, "tick", return_value={"state": "idle"}
                    ) as tick,
                    patch("sys.stdout", io.StringIO()),
                ):
                    runtime.main()
                self.assertEqual(
                    tick.call_args.args[0].interval,
                    helper.DEFAULT_INTERVAL if value is None else value,
                )

    def test_nonpositive_and_noninteger_cli_values_fail_before_dispatch(self):
        for value in (0, -1, "1.5"):
            with tempfile.TemporaryDirectory() as directory:
                with (
                    patch.object(sys, "argv", self.command(Path(directory), value)),
                    patch.object(runtime, "tick") as tick,
                    patch("sys.stderr", io.StringIO()),
                    self.assertRaises(SystemExit) as error,
                ):
                    runtime.main()
                self.assertNotEqual(error.exception.code, 0)
                tick.assert_not_called()
