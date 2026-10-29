"""#830 receipts: a trigger with trailing text is answered by the wrong kind.

Fixture: tests_py/scripts/fixtures/codex_receipts_pr830.json (REST comments on
head 3d3e4f90): "@codex security review" plus an HTML marker at 08:16:09Z was
answered by a code review receipt at 08:17:27Z; the bare trigger at 08:22:29Z
was answered by a security receipt at 08:25:28Z while the summary flags stayed
null.
"""

import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import ci_autopilot_converge_observe as observer  # noqa: E402

DATA = json.loads(
    (Path(__file__).parent / "fixtures/codex_receipts_pr830.json").read_text()
)
HEAD = DATA["head"]
BY_ID = {c["id"]: c for c in DATA["comments"]}


class ReceiptTests(unittest.TestCase):
    def test_marked_trigger_got_a_code_receipt_not_a_security_one(self):
        marked, answer = BY_ID[6491554825], BY_ID[6491578917]
        self.assertNotEqual(marked["body"].strip(), "@codex security review")
        self.assertIn("Codex Review: Didn't find any major issues", answer["body"])
        self.assertIsNone(observer._security_receipt([answer], HEAD))

    def test_bare_trigger_got_a_clean_security_receipt_for_the_head(self):
        bare, answer = BY_ID[6491671127], BY_ID[6491726092]
        self.assertEqual(bare["body"].strip(), "@codex security review")
        self.assertEqual(observer._security_receipt([answer], HEAD), answer["html_url"])

    def test_summary_flags_stayed_null_and_the_security_row_moved(self):
        summary = BY_ID[6478784748]
        state = observer.codex_summary([summary])["security_review"]
        self.assertIsNone(state["has_any_findings"])
        times = {k: v[:19] for k, v in observer.answer_times(summary["body"]).items()}
        marked = BY_ID[6491554825]["created_at"][:19]
        bare = BY_ID[6491671127]["created_at"][:19]
        # The marked security request moved the code row (08:17:29), not the
        # security row; only the bare trigger moved the security row (08:25:29).
        self.assertTrue(marked < times["code_review"] < bare)
        self.assertGreater(times["security_review"], bare)


if __name__ == "__main__":
    unittest.main()
