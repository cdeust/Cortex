"""Reconciliation uses the existing authenticated proof and exact rerun request.

Source: Spec159 finding4395992283 and GitHub's supported Actions event catalog.
"""

import copy
import json
import unittest

from codex_resume_fixtures import OTHER, SHA, comment, state, summary_pages
from test_ci_codex_review_event_fixtures import (
    PREFIX,
    REPO,
    Server,
    invoke,
    invoke_resume,
)


def nullable_summary():
    data = state()
    data["security_review"].update(has_any_findings=True, has_unresolved_findings=None)
    row = comment(data)
    metadata = dict(
        repository=REPO, pullRequestNumber=797, headSha=SHA, status="completed"
    )
    row["body"] += "\n<!-- codex-security-review:v1 " + json.dumps(metadata) + " -->"
    row["body"] += (
        "\n### Security findings\n\n#### Advisory findings (1)\n\n"
        f"- [finding](https://github.com/{REPO}/pull/797#discussion_r1)\n"
    )
    return row


def threads(resolver="cdeust", resolved=True):
    root = dict(
        databaseId=1,
        body="<!-- codex-security-review-finding:v1 -->",
        author=dict(login="chatgpt-codex-connector", __typename="Bot"),
    )
    thread = dict(
        isResolved=resolved,
        resolvedBy=dict(login=resolver, __typename="User"),
        comments=dict(nodes=[root]),
    )
    return dict(
        data=dict(
            repository=dict(
                pullRequest=dict(
                    headRefOid=SHA,
                    reviewThreads=dict(
                        nodes=[thread], pageInfo=dict(hasNextPage=False, endCursor=None)
                    ),
                )
            )
        )
    )


class ReconciliationTests(unittest.TestCase):
    def server(self):
        server = Server()
        server.data["comments"] = [nullable_summary()]
        server.data["threads"] = threads()
        return server

    def trigger(self, sha=SHA):
        return dict(number=797, sha=sha, run_id=None)

    def test_direct_reconciliation_checks_nullable_proof_and_emits_exact_rerun(self):
        server = self.server()
        result, post = invoke_resume(server, self.trigger())
        self.assertEqual(result, dict(action="merge", job_id=21))
        self.assertEqual(len(post), 1)
        self.assertEqual(
            post[0].args[0],
            ["gh", "api", "--method", "POST", PREFIX + "/actions/jobs/21/rerun"],
        )

    def test_nonowner_or_unresolved_threads_never_emit_a_rerun(self):
        for packet in (threads("contributor"), threads(resolved=False)):
            server = self.server()
            server.data["threads"] = packet
            result, post = invoke_resume(server, self.trigger())
            self.assertEqual(result, {"action": "none"})
            self.assertEqual(post, [])

    def test_stale_head_or_unrelated_failure_prevents_reconciliation(self):
        server = self.server()
        self.assertEqual(
            invoke_resume(server, self.trigger(OTHER)), ({"action": "none"}, [])
        )
        server = self.server()
        server.data["jobs"][0]["conclusion"] = "failure"
        self.assertEqual(
            invoke_resume(server, self.trigger()), ({"action": "none"}, [])
        )

    def test_resolution_is_reread_before_any_rerun_request(self):
        server = self.server()
        replies = iter(
            [
                summary_pages([server.data["comments"]]),
                [threads()],
                summary_pages([server.data["comments"]]),
                [threads(resolved=False)],
            ]
        )
        server.overrides["graphql"] = lambda count: copy.deepcopy(next(replies))
        self.assertEqual(
            invoke_resume(server, self.trigger()), ({"action": "none"}, [])
        )

    def test_webhook_only_and_unconfigured_events_cannot_authorize_actions(self):
        for name in ("pull_request_review_thread", "workflow_dispatch"):
            server = self.server()
            result, post = invoke(server, name, payload=dict(action="resolved"))
            self.assertEqual(result, {"action": "none"})
            self.assertEqual(post, [])
            self.assertEqual(server.calls, [])
