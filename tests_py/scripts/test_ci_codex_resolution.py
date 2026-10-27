"""Native PR805 completed-null security verdict, cross-checked against GitHub.

Source: summary6442631163 on0134b085 and GraphQL findings4389092806,
4389808387,4390480666,4391507098, all Bot-authored and isResolved=true.
"""

import json
import subprocess
import unittest
from unittest.mock import patch

from tests_py.scripts.test_ci_codex_reviews import SHA, OTHER, comment, module, state

REPO, PR = "cdeust/Cortex", 805
FINDING = "<!-- codex-security-review-finding:v1 -->"


def summary():
    data = state()
    data["security_review"].update(has_any_findings=True, has_unresolved_findings=None)
    row = comment(data)
    metadata = dict(
        repository=REPO, pullRequestNumber=PR, headSha=SHA, status="completed"
    )
    row["body"] += "\n<!-- codex-security-review:v1 " + json.dumps(metadata) + " -->"
    row["body"] += "\n### Security findings\n\n#### Advisory findings (2)\n\n"
    for identity in (1, 2):
        row["body"] += (
            f"- [finding](https://github.com/{REPO}/pull/{PR}#discussion_r{identity})\n"
        )
    row["body"] += "\n<details>About Codex</details>"
    return row


def page():
    nodes = []
    for identity in (1, 2):
        root = dict(
            databaseId=identity,
            body=FINDING,
            author=dict(login="chatgpt-codex-connector", __typename="Bot"),
        )
        resolver = dict(login="cdeust", __typename="User")
        nodes.append(
            dict(isResolved=True, resolvedBy=resolver, comments=dict(nodes=[root]))
        )
    threads = dict(nodes=nodes, pageInfo=dict(hasNextPage=False, endCursor=None))
    return dict(
        data=dict(
            repository=dict(pullRequest=dict(headRefOid=SHA, reviewThreads=threads))
        )
    )


def thread(packet, index=0):
    return packet["data"]["repository"]["pullRequest"]["reviewThreads"]["nodes"][index]


class ResolvedSecurityTests(unittest.TestCase):
    def evaluate(self, packet=None, row=None):
        m = module()
        with patch.object(
            m.runtime, "_api", return_value=[page() if packet is None else packet]
        ):
            return m.review_evidence([summary() if row is None else row], SHA, REPO, PR)

    def test_completed_null_is_clean_only_with_matching_resolved_native_threads(self):
        result = self.evaluate()
        self.assertEqual(result["state"], "success")
        self.assertTrue(result["reviews_complete"])
        self.assertIsNone(result["security_review"]["has_unresolved_findings"])
        self.assertEqual(result["security_review"]["resolution"]["finding_ids"], [1, 2])
        self.assertEqual(
            result["security_review"]["resolution"]["source"], "github_review_threads"
        )

    def test_unresolved_authenticated_finding_blocks(self):
        packet = page()
        thread(packet)["isResolved"] = False
        result = self.evaluate(packet)
        self.assertEqual(result["state"], "blocked")
        self.assertEqual(result["reason"], "review_unresolved")

    def test_only_the_repository_owner_account_can_resolve_a_finding(self):
        # Codex discussion_r4391948358: a PR author must not dismiss findings.
        for resolver in (
            dict(login="contributor", __typename="User"),
            dict(login="cdeust", __typename="Bot"),
            dict(login="chatgpt-codex-connector", __typename="Bot"),
            None,
        ):
            packet = page()
            thread(packet)["resolvedBy"] = resolver
            with self.subTest(resolver=resolver):
                result = self.evaluate(packet)
                self.assertEqual(result["state"], "blocked")
                self.assertEqual(result["reason"], "review_unresolved")

    def test_unrequested_or_malformed_resolver_never_allows_merge(self):
        for change in (
            lambda t: t.pop("resolvedBy"),
            lambda t: t.update(resolvedBy="cdeust"),
            lambda t: t["resolvedBy"].update(login=None),
        ):
            packet = page()
            change(thread(packet))
            with self.subTest(change=change):
                self.assertEqual(self.evaluate(packet)["state"], "blocked")

    def test_missing_extra_forged_or_malformed_threads_never_allow_merge(self):
        changes = (
            lambda p: thread(p)["comments"]["nodes"][0]["author"].update(
                __typename="User"
            ),
            lambda p: thread(p)["comments"]["nodes"][0]["author"].update(
                login="cdeust"
            ),
            lambda p: thread(p)["comments"]["nodes"][0].update(body="ordinary comment"),
            lambda p: thread(p)["comments"]["nodes"][0].update(databaseId=3),
            lambda p: thread(p).update(isResolved=None),
            lambda p: p["data"]["repository"]["pullRequest"].update(headRefOid=OTHER),
            lambda p: p.update(errors=[{"message": "partial GraphQL response"}]),
            lambda p: p["data"]["repository"]["pullRequest"]["reviewThreads"][
                "pageInfo"
            ].update(hasNextPage=True),
        )
        for change in changes:
            packet = page()
            change(packet)
            with self.subTest(change=change):
                self.assertEqual(self.evaluate(packet)["state"], "blocked")

    def test_running_stale_unknown_or_explicit_verdict_never_uses_resolution(self):
        for field, value in (
            ("status", "running"),
            ("commit_sha", OTHER),
            ("has_any_findings", None),
            ("has_unresolved_findings", True),
        ):
            row = summary()
            data = state()
            data["security_review"].update(
                has_any_findings=True, has_unresolved_findings=None
            )
            data["security_review"][field] = value
            old = (
                row["body"]
                .split("<!-- codex-review-state:v1 ", 1)[1]
                .split(" -->", 1)[0]
            )
            row["body"] = row["body"].replace(old, json.dumps(data))
            m = module()
            with patch.object(
                m.runtime, "_api", side_effect=AssertionError("unexpected API")
            ):
                result = m.review_evidence([row], SHA, REPO, PR)
            self.assertNotEqual(result["state"], "success")

    def test_incomplete_metadata_and_other_pr_links_stay_pending(self):
        for old, new in (
            ("codex-security-review:v1", "unknown:v1"),
            ("/pull/805#", "/pull/806#"),
            ("findings (2)", "findings (3)"),
        ):
            row = summary()
            row["body"] = row["body"].replace(old, new)
            m = module()
            with patch.object(
                m.runtime, "_api", side_effect=AssertionError("unexpected API")
            ):
                self.assertNotEqual(
                    m.review_evidence([row], SHA, REPO, PR)["state"], "success"
                )

    def test_unknown_flag_without_context_stays_pending(self):
        self.assertEqual(module().review_evidence([summary()], SHA)["state"], "pending")

    def test_resolution_api_failure_blocks_without_inventing_a_verdict(self):
        m = module()
        with patch.object(
            m.runtime, "_api", side_effect=m.runtime.EvidenceError("api")
        ):
            result = m.review_evidence([summary()], SHA, REPO, PR)
        self.assertEqual(result["state"], "blocked")
        self.assertEqual(result["reason"], "api")
        self.assertFalse(result["reviews_complete"])

    def test_pagination_covers_every_native_finding_and_rejects_duplicates(self):
        first, second = page(), page()
        connection = first["data"]["repository"]["pullRequest"]["reviewThreads"]
        connection["nodes"] = connection["nodes"][:1]
        connection["pageInfo"].update(hasNextPage=True, endCursor="cursor")
        second["data"]["repository"]["pullRequest"]["reviewThreads"]["nodes"] = [
            thread(second, 1)
        ]
        m = module()
        with patch.object(m.runtime, "_api", return_value=[first, second]):
            self.assertEqual(
                m.review_evidence([summary()], SHA, REPO, PR)["state"], "success"
            )
        thread(second)["comments"]["nodes"][0]["databaseId"] = 1
        with patch.object(m.runtime, "_api", return_value=[first, second]):
            self.assertEqual(
                m.review_evidence([summary()], SHA, REPO, PR)["state"], "blocked"
            )

    def test_cli_reads_threads_and_rechecks_the_live_head(self):
        from tests_py.scripts.test_ci_codex_reviews import pull

        m = module()
        replies = [pull(), [[summary()]], [page()], pull()]
        results = [
            subprocess.CompletedProcess([], 0, json.dumps(row), "") for row in replies
        ]
        with patch.object(m.runtime.subprocess, "run", side_effect=results) as api:
            result = m._fetch(type("Args", (), dict(repo=REPO, pr=PR, sha=SHA)))
        self.assertEqual(result["state"], "success")
        self.assertEqual(len(api.call_args_list), 4)
        graphql = api.call_args_list[2].args[0]
        self.assertIn("graphql", graphql)
        self.assertIn("--paginate", graphql)
        self.assertIn("number=805", graphql)
        self.assertIn("resolvedBy { login __typename }", " ".join(graphql))
