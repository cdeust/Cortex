"""Regression for Codex finding4395405890: old threads survive later reviews."""

import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

RUNTIME = Path(__file__).resolve().parents[2] / "scripts/ci_codex_review_runtime.py"
SHA = "a" * 40
REPO, PR = "owner/project", 464
FINDING = "<!-- codex-security-review-finding:v1 -->"


def native_thread(identity=22, resolved=True, resolver="owner"):
    return {
        "isResolved": resolved,
        "resolvedBy": {"login": resolver, "__typename": "User"},
        "comments": {
            "nodes": [
                {
                    "databaseId": identity,
                    "body": FINDING,
                    "author": {"login": "chatgpt-codex-connector", "__typename": "Bot"},
                }
            ]
        },
    }


def page(threads):
    return {
        "data": {
            "repository": {
                "pullRequest": {
                    "headRefOid": SHA,
                    "reviewThreads": {
                        "nodes": threads,
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                    },
                }
            }
        }
    }


def runtime():
    spec = importlib.util.spec_from_file_location("codex_current_runtime", RUNTIME)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CurrentFindingResolutionTests(unittest.TestCase):
    def evaluate(self, threads, *, metadata=None):
        module = runtime()
        review = dict(
            status="completed",
            commit_sha=SHA,
            has_any_findings=True,
            has_unresolved_findings=None,
        )
        metadata = metadata or dict(
            repository=REPO, pullRequestNumber=PR, headSha=SHA, status="completed"
        )
        body = (
            "\n### Security findings\n\n#### Advisory findings (1)\n\n"
            f"- [finding](https://github.com/{REPO}/pull/{PR}#discussion_r22)\n"
        )
        with patch.object(module, "_api", return_value=[page(threads)]):
            return module.resolve_security((REPO, PR, SHA), body, review, metadata)

    def test_current_resolved_finding_succeeds(self):
        self.assertEqual(
            self.evaluate([native_thread()]),
            {
                "state": "success",
                "source": "github_review_threads",
                "finding_ids": [22],
            },
        )

    def test_historical_findings_do_not_change_the_current_verdict(self):
        for resolved, resolver in (
            (True, "owner"),
            (False, "owner"),
            (True, "contributor"),
        ):
            with self.subTest(resolved=resolved, resolver=resolver):
                result = self.evaluate(
                    [
                        native_thread(11, resolved, resolver),
                        native_thread(22),
                    ]
                )
                self.assertEqual(result["state"], "success")
                self.assertEqual(result["finding_ids"], [22])

    def test_missing_current_finding_cannot_be_replaced_by_old_findings(self):
        with self.assertRaisesRegex(ValueError, "protocol"):
            self.evaluate([native_thread(11)])

    def test_current_unresolved_finding_blocks_despite_resolved_history(self):
        result = self.evaluate([native_thread(11), native_thread(22, False)])
        self.assertEqual(result["state"], "unresolved")
        self.assertEqual(result["finding_ids"], [22])

    def test_current_finding_requires_the_trusted_owner(self):
        for resolver in (
            {"login": "contributor", "__typename": "User"},
            {"login": "owner", "__typename": "Bot"},
            None,
        ):
            current = native_thread()
            current["resolvedBy"] = resolver
            with self.subTest(resolver=resolver):
                self.assertEqual(
                    self.evaluate([native_thread(11), current])["state"], "unresolved"
                )

    def test_forged_current_thread_never_supplies_evidence(self):
        for author in (
            {"login": "owner", "__typename": "User"},
            {"login": "chatgpt-codex-connector", "__typename": "User"},
        ):
            current = native_thread()
            current["comments"]["nodes"][0]["author"] = author
            with (
                self.subTest(author=author),
                self.assertRaisesRegex(ValueError, "protocol"),
            ):
                self.evaluate([native_thread(11), current])

    def test_wrong_repository_pr_or_head_never_uses_resolution(self):
        for field, wrong in (
            ("repository", "other/project"),
            ("pullRequestNumber", 465),
            ("headSha", "b" * 40),
        ):
            metadata = dict(
                repository=REPO, pullRequestNumber=PR, headSha=SHA, status="completed"
            )
            metadata[field] = wrong
            with self.subTest(field=field):
                self.assertIsNone(self.evaluate([native_thread()], metadata=metadata))

    def test_duplicate_or_malformed_threads_remain_protocol_errors(self):
        malformed = native_thread()
        malformed["isResolved"] = None
        for threads in ([native_thread(), native_thread()], [malformed]):
            with (
                self.subTest(threads=threads),
                self.assertRaisesRegex(ValueError, "protocol"),
            ):
                self.evaluate(threads)
