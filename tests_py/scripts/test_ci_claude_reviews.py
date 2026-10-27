"""Adversarial claude[bot] review evidence: one invariant violation per test.

Protocol: the review job of .github/workflows/claude.yml publishes each native
review as a GitHub pull request review on commit_id=<head> whose first body line
is <!-- claude-review:v1 kind=code|security findings=N -->.
"""

from __future__ import annotations

import base64
import copy
import importlib.util
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/ci_claude_reviews.py"
SHA = "a" * 40  # GitHub SHA-1 field, synthetic fixture.
OTHER = "b" * 40
BOT = {"login": "claude[bot]", "type": "Bot"}


def module():
    spec = importlib.util.spec_from_file_location("ci_claude_reviews", SCRIPT)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def review(kind="code", findings=0, review_id=1, **extra):
    """claude[bot] marker review on SHA; extra overrides any REST field."""
    value = {
        "id": review_id,
        "user": copy.deepcopy(BOT),
        "commit_id": SHA,
        "state": "COMMENTED",
        "body": f"<!-- claude-review:v1 kind={kind} findings={findings} -->\n## Review",
    }
    value.update(copy.deepcopy(extra))
    return value


def clean():
    return [review("code", 0, 1), review("security", 0, 2)]


def workflow(mode):
    text = f"name: Claude Code\nenv:\n  CLAUDE_REVIEW_GATE: {mode}\njobs: {{}}\n"
    return {
        "type": "file",
        "encoding": "base64",
        "content": base64.encodebytes(text.encode()).decode(),
    }


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.reader = module()

    def evidence(self, rows, sha=SHA, required=True):
        return self.reader.review_evidence(rows, sha, required)

    def test_both_clean_reviews_on_exact_head_succeed(self):
        result = self.evidence(clean())
        self.assertEqual(
            (result["state"], result["reason"]), ("success", "reviews_complete")
        )
        self.assertTrue(result["reviews_complete"])
        self.assertEqual(result["code"]["review_id"], 1)
        self.assertEqual(result["security"]["review_id"], 2)

    def test_absent_review_is_pending_never_failed(self):
        result = self.evidence([])
        self.assertEqual(
            (result["state"], result["reason"]), ("pending", "review_missing")
        )
        self.assertFalse(result["reviews_complete"])
        result = self.evidence([review("code")])
        self.assertEqual(
            (result["state"], result["reason"]), ("pending", "review_pending")
        )
        self.assertEqual(result["security"]["state"], "pending")

    def test_review_on_stale_sha_is_pending(self):
        result = self.evidence(
            [review("code", commit_id=OTHER), review("security", commit_id=OTHER)]
        )
        self.assertEqual(result["state"], "pending")
        self.assertFalse(result["reviews_complete"])

    def test_marker_review_by_another_identity_is_ignored(self):
        for user in (
            {"login": "github-actions[bot]", "type": "Bot"},
            {"login": "claude[bot]", "type": "User"},
            {"login": "cdeust", "type": "User"},
            None,
        ):
            with self.subTest(user=user):
                rows = [review("code", user=user), review("security", user=user)]
                result = self.evidence(rows)
                self.assertEqual(
                    (result["state"], result["reason"]), ("pending", "review_missing")
                )

    def test_findings_block_until_a_new_head(self):
        result = self.evidence([review("code", 2, 1), review("security", 0, 2)])
        self.assertEqual(
            (result["state"], result["reason"]), ("blocked", "review_unresolved")
        )
        self.assertTrue(result["reviews_complete"])
        self.assertEqual(result["code"]["findings"], 2)

    def test_malformed_marker_fails(self):
        for body in (
            "<!-- claude-review:v1 kind=other findings=0 -->",
            "<!-- claude-review:v1 kind=code findings=abc -->",
            "<!-- claude-review:v1 kind=code findings=01 -->",
            "<!-- claude-review:v2 kind=code findings=0 -->",
            "<!-- claude-review:v1 kind=code findings=0 --> trailing",
            "<!-- claude-review:v1 kind=code findings=-1 -->\nbody",
        ):
            with self.subTest(body=body):
                rows = clean() + [review(review_id=3, body=body)]
                result = self.evidence(rows)
                self.assertEqual(
                    (result["state"], result["reason"]), ("blocked", "review_failed")
                )
                self.assertFalse(result["reviews_complete"])

    def test_duplicate_kind_on_one_head_fails_instead_of_latest_wins(self):
        rows = [review("code", 3, 1), review("code", 0, 4), review("security", 0, 2)]
        result = self.evidence(rows)
        self.assertEqual(
            (result["state"], result["reason"]), ("blocked", "review_failed")
        )
        self.assertEqual(result["code"]["state"], "failed")

    def test_non_comment_review_state_fails(self):
        for state in ("APPROVED", "CHANGES_REQUESTED", "DISMISSED"):
            with self.subTest(state=state):
                rows = [review("code", state=state), review("security", 0, 2)]
                result = self.evidence(rows)
                self.assertEqual(result["reason"], "review_failed")

    def test_unrelated_reviews_and_comments_are_ignored(self):
        rows = clean() + [
            review(review_id=7, body="LGTM"),
            review(review_id=8, body=None),
            review(review_id=9, user={"login": "cdeust", "type": "User"}, body="ok"),
        ]
        self.assertEqual(self.evidence(rows)["state"], "success")

    def test_malformed_api_rows_block_with_protocol(self):
        for mutate in (
            lambda row: row.update(id=0),
            lambda row: row.update(id=True),
            lambda row: row.update(commit_id="short"),
            lambda row: row.update(body=5),
            lambda row: row.update(state=None),
            lambda row: row.update(user="claude[bot]"),
        ):
            rows = clean()
            mutate(rows[0])
            result = self.evidence(rows)
            self.assertEqual(
                (result["state"], result["reason"]), ("blocked", "protocol")
            )
        self.assertEqual(self.evidence("rows")["reason"], "protocol")
        self.assertEqual(self.evidence(clean(), sha="nope")["reason"], "arguments")

    def test_not_required_is_a_distinct_state_and_reads_nothing(self):
        result = self.evidence("unused", required=False)
        self.assertEqual(
            (result["state"], result["reason"]), ("not_required", "not_required")
        )
        self.assertFalse(result["reviews_complete"])
        self.assertIs(result["required"], False)


class GateTests(unittest.TestCase):
    def setUp(self):
        self.reader = module()

    def test_gate_line_decides_activation(self):
        mode = self.reader.gate_mode
        self.assertTrue(mode("env:\n  CLAUDE_REVIEW_GATE: required\n"))
        self.assertFalse(mode("env:\n  CLAUDE_REVIEW_GATE: observe\n"))
        self.assertFalse(mode("name: Claude Code\n# CLAUDE_REVIEW_GATE: required\n"))
        for text in (
            "env:\n  CLAUDE_REVIEW_GATE: maybe\n",
            "env:\n  CLAUDE_REVIEW_GATE: required\n  CLAUDE_REVIEW_GATE: observe\n",
        ):
            with self.subTest(text=text), self.assertRaises(self.reader.EvidenceError):
                mode(text)

    def test_main_workflow_listing_is_the_trust_anchor(self):
        calls = []

        def api(endpoint, **_):
            calls.append(endpoint)
            if endpoint.endswith("/contents/.github/workflows?ref=main"):
                return listing
            return content

        listing, content = [{"name": "pipeline.yml", "type": "file"}], None
        self.assertFalse(self.reader.read_gate("cdeust/Cortex", api))
        self.assertEqual(
            calls, ["repos/cdeust/Cortex/contents/.github/workflows?ref=main"]
        )
        listing = [{"name": "claude.yml", "type": "file"}]
        for mode, expected in (("observe", False), ("required", True)):
            content = workflow(mode)
            self.assertIs(self.reader.read_gate("cdeust/Cortex", api), expected)
        self.assertEqual(
            calls[-1],
            "repos/cdeust/Cortex/contents/.github/workflows/claude.yml?ref=main",
        )

    def test_unreadable_gate_blocks_instead_of_falling_back(self):
        def server(listing, content):
            def api(endpoint, **_):
                return content if "claude.yml" in endpoint else listing

            return api

        listing = [{"name": "claude.yml", "type": "file"}]
        for content in (
            {"encoding": "none", "content": ""},
            {"encoding": "base64", "content": "!!!"},
            {"encoding": "base64", "content": base64.b64encode(b"\xff").decode()},
            [],
        ):
            with (
                self.subTest(content=content),
                self.assertRaises(self.reader.EvidenceError),
            ):
                self.reader.read_gate("cdeust/Cortex", server(listing, content))
        for bad in ("x", [{"name": 1}], [{"name": "claude.yml", "type": "dir"}]):
            with (
                self.subTest(listing=bad),
                self.assertRaises(self.reader.EvidenceError),
            ):
                self.reader.read_gate("cdeust/Cortex", server(bad, None))


if __name__ == "__main__":
    unittest.main()
