"""combined_proof: Codex alone until main requires Claude, then both."""

from __future__ import annotations

import unittest

from tests_py.scripts.test_ci_claude_reviews import (
    OTHER,
    TOKEN,
    SHA,
    clean,
    module,
    producer,
    review,
)


class CombineTests(unittest.TestCase):
    """scripts/ci_codex_review_resume.py combined_proof over both readers."""

    def setUp(self):
        from tests_py.scripts.test_ci_codex_review_resume import load_policy

        self.reader = module()
        self.combine = load_policy().combined_proof
        self.jobs = {TOKEN: producer()}

    def claude(self, rows):
        return self.reader.review_evidence(rows, SHA, self.jobs.get)

    def codex(self, state="success", reason="reviews_complete", complete=True):
        return {
            "state": state,
            "reason": reason,
            "sha": SHA,
            "reviews_complete": complete,
        }

    def test_not_required_returns_codex_proof_unchanged(self):
        codex = self.codex()
        # The handler's shape when main's gate is absent or observe.
        claude = {"state": "not_required", "reason": "not_required", "sha": SHA}
        self.assertIs(self.combine(codex, claude), codex)

    def test_required_claude_pending_keeps_proof_incomplete(self):
        claude = self.claude([])
        proof = self.combine(self.codex(), claude)
        self.assertEqual(proof["state"], "pending")
        self.assertFalse(proof["reviews_complete"])

    def test_both_complete_success_and_unresolved(self):
        proof = self.combine(self.codex(), self.claude(clean()))
        self.assertEqual(
            (proof["state"], proof["reason"]), ("success", "reviews_complete")
        )
        self.assertTrue(proof["reviews_complete"])
        findings = [review("code", 1, 1), review("security", 0, 2)]
        proof = self.combine(self.codex(), self.claude(findings))
        self.assertEqual(
            (proof["state"], proof["reason"]), ("blocked", "review_unresolved")
        )
        self.assertTrue(proof["reviews_complete"])

    def test_codex_failure_or_sha_mismatch_never_completes(self):
        claude = self.claude(clean())
        proof = self.combine(self.codex("blocked", "review_failed", False), claude)
        self.assertEqual(
            (proof["state"], proof["reason"]), ("blocked", "review_failed")
        )
        other = dict(self.codex(), sha=OTHER)
        proof = self.combine(other, claude)
        self.assertEqual((proof["state"], proof["reason"]), ("blocked", "protocol"))
        self.assertFalse(proof["reviews_complete"])


if __name__ == "__main__":
    unittest.main()
