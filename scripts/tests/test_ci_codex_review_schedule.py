"""The supported fallback queues only an already justified native gate rerun."""

import contextlib
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from codex_resume_fixtures import OTHER, SHA, state, comment
from test_ci_codex_review_event_fixtures import REPO, PULL, Server

SCRIPT = Path(__file__).resolve().parents[1] / "ci_codex_review_reconcile.py"
OPEN = "graphql"


def load():
    spec = importlib.util.spec_from_file_location("codex_reconcile", SCRIPT)
    target = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(target)
    return target


def discovery_node(server, row):
    if "isDraft" in row:
        return copy.deepcopy(row)
    checks = [
        dict(
            __typename="CheckRun",
            name=j["name"],
            status=j["status"].upper(),
            conclusion=j["conclusion"].upper(),
        )
        for j in server.data["jobs"]
    ]
    if server.data["source"]["status"] != "completed":
        checks[-2]["status"] = "IN_PROGRESS"
    head = row.get("head", {})
    commit = dict(
        oid=head.get("sha"),
        statusCheckRollup=dict(
            contexts=dict(nodes=checks, pageInfo=dict(hasNextPage=False))
        ),
    )
    return dict(
        number=row["number"],
        isDraft=row.get("draft"),
        isCrossRepository=False,
        title=row.get("title", ""),
        headRefOid=head.get("sha"),
        headRepository=dict(nameWithOwner=head.get("repo", {}).get("full_name")),
        labels=dict(nodes=row.get("labels", [])),
        commits=dict(nodes=[dict(commit=commit)]),
    )


def discovery_pages(server, pages):
    result = []
    for index, rows in enumerate(pages):
        if not isinstance(rows, list):
            result.append(rows)
            continue
        nodes = [discovery_node(server, row) for row in rows]
        result.append(
            dict(
                data=dict(
                    repository=dict(
                        nameWithOwner=REPO,
                        pullRequests=dict(
                            nodes=nodes,
                            pageInfo=dict(
                                hasNextPage=index < len(pages) - 1, endCursor=str(index)
                            ),
                        ),
                    )
                )
            )
        )
    return result


class ScheduledReconciliationTests(unittest.TestCase):
    def invoke(self, server, pages=None, flags=None):
        target = load()

        def request(endpoint, *, paginate=False, fields=None):
            if endpoint == "graphql" and "statusCheckRollup" in (fields or {}).get(
                "query", ""
            ):
                server.calls.append(("discovery", paginate))
                return discovery_pages(
                    server, [[server.data["pull"]]] if pages is None else pages
                )
            return server(endpoint, paginate=paginate, fields=fields)

        out, err = io.StringIO(), io.StringIO()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            env = dict(
                GITHUB_REPOSITORY=REPO,
                GH_TOKEN="PRIVATE_TOKEN",
                GITHUB_OUTPUT=str(output),
                EXPECTED_PR="797",
            )
            with (
                patch.dict(os.environ, env),
                patch.object(target.events.source, "_api", side_effect=request),
                patch.object(
                    sys.modules["ci_codex_review_runtime"], "_api", side_effect=request
                ),
                patch.object(target.events.subprocess, "run") as post,
                contextlib.redirect_stdout(out),
                contextlib.redirect_stderr(err),
            ):
                code = target.main(["--list"] if flags is None else flags)
            return (
                code,
                out.getvalue(),
                err.getvalue(),
                (output.read_text() if output.exists() else ""),
                post.call_args_list,
            )

    def test_discovery_reads_all_pages_and_does_not_post(self):
        server = Server()
        result = self.invoke(server, [[], [server.data["pull"]]])
        self.assertEqual(result[0], 0, result[2])
        expected = [dict(number=797, sha=SHA)]
        self.assertEqual(json.loads(result[1]), expected)
        self.assertEqual(json.loads(result[3].split("=", 1)[1]), expected)
        self.assertEqual(result[4], [])
        self.assertIn(("discovery", True), server.calls)

    def test_inflight_tests_and_unrelated_failures_do_not_create_matrix_jobs(self):
        for kind in ("running", "failed_prerequisite", "unrelated"):
            server = Server()
            if kind == "running":
                server.data["source"].update(status="in_progress", conclusion=None)
            elif kind == "failed_prerequisite":
                server.data["jobs"][0]["conclusion"] = "failure"
            else:
                row = copy.deepcopy(server.data["jobs"][0])
                row.update(id=99, name="unrelated", conclusion="failure")
                server.data["jobs"].append(row)
            result = self.invoke(server)
            self.assertEqual(json.loads(result[1]), [])
            self.assertEqual(result[4], [])

    def test_drafts_forks_holds_and_stale_heads_never_queue(self):
        for kind in ("draft", "fork", "hold", "stale"):
            server = Server()
            row = copy.deepcopy(server.data["pull"])
            if kind == "draft":
                row["draft"] = True
            elif kind == "fork":
                row["head"]["repo"]["full_name"] = "other/fork"
            elif kind == "hold":
                server.data["pull"]["title"] = "DO NOT MERGE"
            else:
                changed = copy.deepcopy(row)
                changed["head"]["sha"] = OTHER
                server.overrides[PULL] = lambda count, row=changed: row
            result = self.invoke(server, [[row]])
            self.assertEqual(json.loads(result[1]), [])
            self.assertEqual(result[4], [])

    def test_incomplete_or_untrusted_summary_never_queues(self):
        for kind in ("pending", "human_editor"):
            server = Server()
            data = state()
            data["security_review"]["status"] = "running"
            row = comment(data) if kind == "pending" else comment()
            if kind == "human_editor":
                row.update(
                    editor=dict(login="writer", __typename="User", id="human"),
                    lastEditedAt="2026-10-28T00:00:00Z",
                )
            server.data["comments"] = [row]
            result = self.invoke(server)
            self.assertEqual(json.loads(result[1]), [])
            self.assertEqual(result[4], [])

    def test_one_malformed_pr_does_not_starve_a_valid_one(self):
        server = Server()
        bad = dict(number=798, state="open", draft=False)
        result = self.invoke(server, [[bad, server.data["pull"]]])
        self.assertEqual(json.loads(result[1]), [dict(number=797, sha=SHA)])
        self.assertIn("protocol", result[2])
        self.assertEqual(result[4], [])

    def test_real_api_failure_stops_scan_before_another_pr(self):
        server = Server()
        bad = copy.deepcopy(server.data["pull"])
        bad["number"] = 798

        def fail(count):
            raise load().events.source.EvidenceError("api")

        server.overrides[f"repos/{REPO}/pulls/798"] = fail
        result = self.invoke(server, [[bad, server.data["pull"]]])
        self.assertEqual(result[0], 1)
        self.assertEqual(result[3], "")
        self.assertIn("api", result[2])
        self.assertNotIn((PULL, False), server.calls)
        self.assertEqual(result[4], [])

    def test_duplicate_pr_is_rejected_without_hiding_another(self):
        server = Server()
        bad = copy.deepcopy(server.data["pull"])
        bad["number"] = 798
        result = self.invoke(server, [[bad], [bad, server.data["pull"]]])
        self.assertEqual(json.loads(result[1]), [dict(number=797, sha=SHA)])
        self.assertIn("protocol", result[2])

    def test_malformed_global_pagination_fails_before_any_queue(self):
        server = Server()
        result = self.invoke(server, [[server.data["pull"]], {}])
        self.assertEqual(result[0], 1)
        self.assertEqual(result[3], "")
        self.assertEqual(result[4], [])

    def test_worker_rechecks_full_proof_and_posts_only_exact_waiting_job(self):
        result = self.invoke(Server(), flags=["--pr", "797", "--sha", SHA])
        self.assertEqual(result[0], 0, result[2])
        self.assertEqual(json.loads(result[1]), dict(action="merge", job_id=21))
        self.assertEqual(
            result[4][0].args[0],
            ["gh", "api", "--method", "POST", f"repos/{REPO}/actions/jobs/21/rerun"],
        )

    def test_worker_rejects_moved_head_and_missing_auth(self):
        result = self.invoke(Server(), flags=["--pr", "797", "--sha", OTHER])
        self.assertEqual(json.loads(result[1]), {"action": "none"})
        self.assertEqual(result[4], [])
        target = load()
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(target.events.source, "_api") as api,
        ):
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(target.main(["--list"]), 1)
            api.assert_not_called()

    def test_rollup_rejects_nonwaiters_before_any_rest_call(self):
        for kind in ("draft", "fork", "hold", "inflight", "green"):
            server = Server()
            row = discovery_pages(server, [[server.data["pull"]]])[0]["data"][
                "repository"
            ]["pullRequests"]["nodes"][0]
            checks = row["commits"]["nodes"][0]["commit"]["statusCheckRollup"][
                "contexts"
            ]["nodes"]
            if kind == "draft":
                row["isDraft"] = True
            elif kind == "fork":
                row["isCrossRepository"] = True
            elif kind == "hold":
                row["title"] = "DO NOT MERGE"
            elif kind == "inflight":
                checks[-2]["status"] = "IN_PROGRESS"
            elif kind == "green":
                checks[-1]["conclusion"] = "SUCCESS"
            result = self.invoke(server, [[row]])
            self.assertEqual(json.loads(result[1]), [], kind)
            self.assertEqual(server.calls, [("discovery", True)], kind)

    def test_failed_test_readiness_repair_is_queued_by_real_policy(self):
        server = Server()
        server.data["jobs"][1]["conclusion"] = "failure"
        review = server.data["jobs"][-2]
        review.update(
            conclusion="failure",
            steps=[dict(name="Require completed Codex reviews", conclusion="failure")],
        )
        result = self.invoke(server)
        self.assertEqual(json.loads(result[1]), [dict(number=797, sha=SHA)])
        worker = self.invoke(server, flags=["--pr", "797", "--sha", SHA])
        self.assertEqual(json.loads(worker[1]), dict(action="review", job_id=20))

    def test_review_held_pr_is_queued_and_resumed(self):
        # Owner rule 2026-10-29: only the owner's holds stay out of the queue.
        server = Server()
        server.data["pull"]["labels"] = [{"name": "hold"}, {"name": "autopilot:hold"}]
        result = self.invoke(server)
        self.assertEqual(json.loads(result[1]), [dict(number=797, sha=SHA)])
        worker = self.invoke(server, flags=["--pr", "797", "--sha", SHA])
        self.assertEqual(json.loads(worker[1]), dict(action="merge", job_id=21))

    def test_claude_verdict_arrival_resumes_the_pending_gate(self):
        # Codex completed; the gate waits ("merge pending review") for Claude.
        server = Server()
        server.data["pull"]["labels"] = [{"name": "hold"}]
        server.data["source"]["conclusion"] = "success"
        server.data["jobs"][-1].update(name="merge pending review", conclusion="success", steps=[])
        server.data["claude"] = False
        self.assertEqual(json.loads(self.invoke(server)[1]), [])
        server.data["claude"] = True  # the claude-review-verdict:v1 marker for the head
        self.assertEqual(json.loads(self.invoke(server)[1]), [dict(number=797, sha=SHA)])
        worker = self.invoke(server, flags=["--pr", "797", "--sha", SHA])
        self.assertEqual(json.loads(worker[1]), dict(action="review", job_id=20))

    def test_quota_wait_is_reconsidered_when_codex_comments_again(self):
        # Rule D6: a usage-limit notice keeps the gate pending, not failed.
        # source: cdeust/ai-architect-mcp-spec PR164 comment6497379059, verbatim.
        notice = comment(comment_id=7, updated="2026-10-26T22:30:00Z")
        notice["body"] = (
            "You have reached your Codex usage limits for code reviews. You can see your "
            "limits in the [Codex usage dashboard](https://chatgpt.com/codex/cloud/settings/usage)."
        )
        failed = state()
        failed["code_review"].update(status="failed", has_any_findings=None,
                                     has_unresolved_findings=None)
        server = Server()
        server.data["source"]["conclusion"] = "success"
        server.data["jobs"][-1].update(name="merge pending review", conclusion="success", steps=[])
        server.data["comments"] = [comment(failed), notice]
        self.assertEqual(json.loads(self.invoke(server)[1]), [])
        server.data["comments"] = [comment(updated="2026-10-26T23:00:00Z"), notice]
        self.assertEqual(json.loads(self.invoke(server)[1]), [dict(number=797, sha=SHA)])
        worker = self.invoke(server, flags=["--pr", "797", "--sha", SHA])
        self.assertEqual(json.loads(worker[1]), dict(action="review", job_id=20))

    def test_owner_label_hold_is_never_queued(self):
        server = Server()
        server.data["pull"]["labels"] = [{"name": "hold"}, {"name": "do-not-merge"}]
        result = self.invoke(server)
        self.assertEqual(json.loads(result[1]), [])
        self.assertEqual(server.calls, [("discovery", True)])

    def test_discovery_does_not_repeat_live_pr_read(self):
        server = Server()
        result = self.invoke(server)
        self.assertEqual(result[0], 0, result[2])
        self.assertEqual(server.calls.count((PULL, False)), 1)
