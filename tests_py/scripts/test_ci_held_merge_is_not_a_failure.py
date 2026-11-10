"""A merge that waits ends the resolver green, with a notice (ADR-1128)."""

import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import textwrap
import unittest
import unittest.mock

ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / ".github/workflows/pipeline-post-merge.yml"


def resolver():
    text = ENGINE.read_text()
    source = text.split("          python3 - <<'PY'\n", 1)[1].split(
        "\n          PY", 1
    )[0]
    namespace = {"__name__": "resolver_test"}
    exec(compile(textwrap.dedent(source), "trusted_resolver", "exec"), namespace)
    return namespace


def run_main(outcome):
    """Exit code, stdout, stderr and outputs of main() when resolve() ends in outcome."""
    ns = resolver()

    def resolve(*_):
        if isinstance(outcome, str):
            raise ns["PostMergeError"](outcome)
        return outcome

    ns["resolve"] = resolve
    with tempfile.TemporaryDirectory() as tmp:
        event, output = Path(tmp) / "event.json", Path(tmp) / "output"
        event.write_text(json.dumps({}))
        output.write_text("")
        env = {
            "GITHUB_EVENT_NAME": "workflow_run",
            "GITHUB_EVENT_PATH": str(event),
            "GITHUB_REPOSITORY": "o/r",
            "GH_TOKEN": "t",
            "GITHUB_OUTPUT": str(output),
        }
        out, err = io.StringIO(), io.StringIO()
        with (
            unittest.mock.patch.dict(os.environ, env),
            contextlib.redirect_stdout(out),
            contextlib.redirect_stderr(err),
        ):
            code = ns["main"]()
        return code, out.getvalue(), err.getvalue(), output.read_text()


WAITS = (
    "merge held: Pipeline has not succeeded on this head",
    "merge held: no Claude review ran on this head",
    "merge held: Claude has not posted a verdict on this head",
    "merge held: Claude review verdict is block",
    "PR head advanced after testing",
)


class HeldMergeTests(unittest.TestCase):
    def test_a_waiting_merge_is_green_and_writes_no_output(self):
        for reason in WAITS:
            with self.subTest(reason=reason):
                code, out, err, outputs = run_main(reason)
                self.assertEqual(code, 0)
                self.assertIn(f"::notice title=Merge not made::{reason}", out)
                self.assertEqual((err, outputs), ("", ""))

    def test_every_waiting_reason_of_the_resolver_is_covered(self):
        source = ENGINE.read_text()
        for reason in WAITS:
            self.assertIn(f'"{reason}"', source)
        held = set(__import__("re").findall(r'"(merge held: [^"]+)"', source))
        self.assertEqual(held, {r for r in WAITS if r.startswith("merge held:")})

    def test_any_other_refusal_still_fails(self):
        for reason in (
            "PR label holds merge",
            "source merge gate requires completed unit",
            "GitHub did not confirm a completed merge",
            "PR is closed or draft",
        ):
            with self.subTest(reason=reason):
                code, out, err, outputs = run_main(reason)
                self.assertEqual(code, 1)
                self.assertIn(f"post-merge: {reason}", err)
                self.assertEqual(outputs, "")

    def test_a_merge_still_writes_its_outputs(self):
        result = {
            "tested_sha": "c" * 40,
            "run_tests": "true",
            "pr_number": "7",
            "reason": "x",
        }
        code, _, _, outputs = run_main(result)
        self.assertEqual(code, 0)
        self.assertIn("pr_number=7\n", outputs)

    def test_no_job_runs_after_a_waiting_resolver(self):
        text = ENGINE.read_text()
        closer = text.split("\n  close-issues:\n", 1)[1].split("\n    runs-on:", 1)[0]
        self.assertIn("needs.resolve.outputs.pr_number != ''", closer)
        contract = text.split("\n  contract:\n", 1)[1].split("\n    runs-on:", 1)[0]
        self.assertIn("needs.resolve.outputs.run_tests == 'true'", contract)


if __name__ == "__main__":
    unittest.main()
