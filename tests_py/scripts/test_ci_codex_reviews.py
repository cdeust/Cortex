"""Adversarial Codex evidence cases and authenticated gh-boundary behavior.

Protocol source: Cortex PR797 canonical bot summary, comment6428675514.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/ci_codex_reviews.py"
SHA = "a" * 40
OTHER = "b" * 40
SUMMARY = "<!-- codex-pull-request-review-summary -->"
STATE = "<!-- codex-review-state:v1 "


def state(sha=SHA):
    review = {
        "commit_sha": sha,
        "status": "completed",
        "has_any_findings": False,
        "has_unresolved_findings": False,
    }
    return {
        "code_review": copy.deepcopy(review),
        "security_review": copy.deepcopy(review),
    }


def comment(data=None, comment_id=1, updated="2026-10-26T22:00:00Z"):
    return {
        "id": comment_id,
        "updated_at": updated,
        "user": {"login": "chatgpt-codex-connector[bot]", "type": "Bot"},
        "body": SUMMARY
        + "\n"
        + STATE
        + json.dumps(state() if data is None else data)
        + " -->",
    }


def pull():
    return {
        "number": 797,
        "state": "open",
        "draft": False,
        "head": {"sha": SHA, "repo": {"full_name": "cdeust/Cortex"}},
        "base": {"ref": "main", "repo": {"full_name": "cdeust/Cortex"}},
    }


def module():
    spec = importlib.util.spec_from_file_location("ci_codex_reviews", SCRIPT)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


class CodexEvidenceTests(unittest.TestCase):
    def evidence(self, comments):
        return module().review_evidence(comments, SHA)

    def test_both_current_reviews_are_required(self):
        for code_sha, security_sha in (
            (SHA, SHA),
            (OTHER, SHA),
            (SHA, OTHER),
            (OTHER, OTHER),
        ):
            data = state()
            data["code_review"]["commit_sha"] = code_sha
            data["security_review"]["commit_sha"] = security_sha
            expected = "success" if code_sha == security_sha == SHA else "pending"
            self.assertEqual(self.evidence([comment(data)])["state"], expected)

    def test_missing_and_partial_security_review_stay_pending(self):
        for value in (
            None,
            {},
            {"status": None},
            {"status": "queued", "commit_sha": SHA},
            {
                "status": "running",
                "commit_sha": SHA,
                "has_any_findings": None,
                "has_unresolved_findings": None,
            },
        ):
            data = state()
            data["security_review"] = value
            self.assertEqual(self.evidence([comment(data)])["state"], "pending")
        self.assertEqual(self.evidence([])["state"], "pending")
        data = state()
        del data["security_review"]
        self.assertEqual(self.evidence([comment(data)])["state"], "pending")

    def test_completed_review_missing_fields_or_unknown_bools_blocks(self):
        for value in (None, 0, 1, "", "false", [], {}):
            data = state()
            data["security_review"]["has_unresolved_findings"] = value
            self.assertEqual(self.evidence([comment(data)])["state"], "blocked")
        for field in ("commit_sha", "has_any_findings", "has_unresolved_findings"):
            data = state()
            del data["security_review"][field]
            self.assertEqual(self.evidence([comment(data)])["state"], "blocked")

    def test_pending_fields_cannot_have_malformed_types(self):
        for value in (0, 1, [], "false"):
            data = state()
            data["code_review"].update(status="running", has_any_findings=value)
            self.assertEqual(self.evidence([comment(data)])["state"], "blocked")

    def test_failed_and_unknown_statuses_block(self):
        for value in ("failed", "error", "cancelled", "unknown", 1, False, [], {}):
            data = state()
            data["code_review"]["status"] = value
            self.assertEqual(self.evidence([comment(data)])["state"], "blocked")

    def test_failed_review_exposes_sanitized_terminal_status(self):
        data = state()
        data["code_review"]["status"] = "failed"
        result = self.evidence([comment(data)])
        self.assertEqual(result["code_review"]["status"], "failed")
        self.assertEqual(result["reason"], "review_failed")
        self.assertFalse(result["reviews_complete"])

    def test_complete_metadata_is_exposed_without_raw_comment_content(self):
        data = state()
        data["security_review"].update(
            has_any_findings=True, has_unresolved_findings=True
        )
        item = comment(data)
        item["body"] += "\nPRIVATE_TOKEN"
        result = self.evidence([item])
        self.assertTrue(result["reviews_complete"])
        self.assertEqual(result["updated_at"], item["updated_at"])
        self.assertEqual(result["security_review"], data["security_review"])
        self.assertNotIn("PRIVATE_TOKEN", json.dumps(result))

    def test_unresolved_findings_block_but_resolved_findings_pass(self):
        data = state()
        data["security_review"]["has_any_findings"] = True
        self.assertEqual(self.evidence([comment(data)])["state"], "success")
        data["security_review"]["has_unresolved_findings"] = True
        self.assertEqual(self.evidence([comment(data)])["state"], "blocked")
        data["security_review"]["has_any_findings"] = False
        self.assertEqual(self.evidence([comment(data)])["state"], "blocked")

    def test_spoofed_authors_and_noncanonical_comments_are_ignored(self):
        for user in (
            {"login": "cdeust", "type": "User"},
            {"login": "chatgpt-codex-connector[bot]", "type": "User"},
            {"login": "other[bot]", "type": "Bot"},
            None,
        ):
            item = comment()
            item["user"] = user
            self.assertEqual(self.evidence([item])["state"], "pending")
        item = comment()
        item["body"] = "quoted " + item["body"]
        self.assertEqual(self.evidence([item])["state"], "pending")

    def test_latest_canonical_summary_wins_and_cannot_fallback_when_malformed(self):
        old = comment(comment_id=99)
        latest = comment(comment_id=1, updated="2026-10-26T22:01:00Z")
        latest["body"] = SUMMARY + "\n" + STATE + "{PRIVATE_TOKEN -->"
        self.assertEqual(self.evidence([latest, old])["state"], "blocked")
        latest = comment(state(OTHER), 1, "2026-10-26T22:01:00Z")
        self.assertEqual(self.evidence([latest, old])["state"], "pending")
        tied = comment(state(OTHER), 100)
        self.assertEqual(self.evidence([tied, old])["comment_id"], 100)

    def test_duplicate_json_keys_and_protocol_markers_block(self):
        item = comment()
        item["body"] = item["body"].replace(
            '"code_review":', '"code_review":null,"code_review":', 1
        )
        self.assertEqual(self.evidence([item])["state"], "blocked")
        for suffix in (
            comment()["body"],
            STATE + "{} -->",
            "<!-- codex-review-state:v2 {} -->",
            "<!-- codex-security-review:v1 {} -->\n"
            "<!-- codex-security-review:v1 {} -->",
        ):
            item = comment()
            item["body"] += "\n" + suffix
            self.assertEqual(self.evidence([item])["state"], "blocked")

    def test_nonstandard_json_constants_and_excessive_integer_are_blocked(self):
        digits = sys.get_int_max_str_digits() or sys.int_info.str_digits_check_threshold
        for raw in ("NaN", "Infinity", "9" * (digits + 1)):
            item = comment()
            item["body"] = (
                SUMMARY + "\n" + STATE + '{"code_review":{"status":' + raw + "}} -->"
            )
            self.assertEqual(self.evidence([item])["state"], "blocked")

    def test_malformed_optional_security_marker_blocks(self):
        item = comment()
        item["body"] += '\n<!-- codex-security-review:v1 {"a":1,"a":2} -->'
        self.assertEqual(self.evidence([item])["state"], "blocked")

    def test_invalid_comment_metadata_or_state_shape_blocks(self):
        for key, value in (
            ("id", True),
            ("id", 0),
            ("updated_at", "PRIVATE_TOKEN"),
            ("updated_at", None),
        ):
            item = comment()
            item[key] = value
            self.assertEqual(self.evidence([item])["state"], "blocked")
        for value in ([], False, "PRIVATE_TOKEN"):
            item = comment()
            item["body"] = SUMMARY + "\n" + STATE + json.dumps(value) + " -->"
            self.assertEqual(self.evidence([item])["state"], "blocked")
        self.assertEqual(self.evidence({})["state"], "blocked")


if __name__ == "__main__":
    unittest.main()
