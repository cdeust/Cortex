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

from tests_py.scripts.test_ci_codex_reviews import OTHER, SHA, state, comment
from tests_py.scripts.test_ci_codex_review_event_fixtures import REPO, PULL, Server

SCRIPT = (
    Path(__file__).resolve().parents[2] / "scripts" / "ci_codex_review_reconcile.py"
)
OPEN = f"repos/{REPO}/pulls?state=open&per_page=100"


def load():
    spec = importlib.util.spec_from_file_location("codex_reconcile", SCRIPT)
    target = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(target)
    return target


class ScheduledReconciliationTests(unittest.TestCase):
    def invoke(self, server, pages=None, flags=None):
        target = load()
        server.overrides[OPEN] = lambda count: (
            [[server.data["pull"]]] if pages is None else pages
        )
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
                patch.object(target.events.source, "_api", side_effect=server),
                patch.object(
                    sys.modules["ci_codex_review_runtime"], "_api", side_effect=server
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
        self.assertIn((OPEN, True), server.calls)

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

    def test_one_pr_api_failure_is_sanitized_without_starving_another(self):
        server = Server()
        bad = copy.deepcopy(server.data["pull"])
        bad["number"] = 798

        def fail(count):
            raise OSError("PRIVATE_TOKEN")

        server.overrides[f"repos/{REPO}/pulls/798"] = fail
        result = self.invoke(server, [[bad, server.data["pull"]]])
        self.assertEqual(json.loads(result[1]), [dict(number=797, sha=SHA)])
        self.assertIn("api", result[2])
        self.assertNotIn("PRIVATE_TOKEN", result[2])

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
