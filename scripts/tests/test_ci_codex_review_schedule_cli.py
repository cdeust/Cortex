"""Exercise reconciliation CLI boundaries without mocking its authorization policy."""

import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from codex_resume_fixtures import SHA
from test_ci_codex_review_event_fixtures import REPO, Server
import test_ci_codex_review_schedule as schedule

SCRIPT = Path(__file__).resolve().parents[1] / "ci_codex_review_reconcile.py"


def load():
    spec = importlib.util.spec_from_file_location("codex_reconcile_cli", SCRIPT)
    target = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(target)
    return target


class ReconciliationBoundaryTests(unittest.TestCase):
    def invoke(self, flags, env):
        target = load()
        err = io.StringIO()
        pages = [
            dict(
                data=dict(
                    repository=dict(
                        nameWithOwner=REPO,
                        pullRequests=dict(
                            nodes=[], pageInfo=dict(hasNextPage=False, endCursor=None)
                        ),
                    )
                )
            )
        ]
        with (
            patch.dict(os.environ, env, clear=True),
            patch.object(target.events.source, "_api", return_value=pages) as api,
            patch.object(target.events.subprocess, "run") as post,
            contextlib.redirect_stderr(err),
        ):
            code = target.main(flags)
        return code, err.getvalue(), api.call_count, post.call_count

    def test_invalid_worker_grammar_never_reads_or_posts(self):
        env = dict(GITHUB_REPOSITORY=REPO, GH_TOKEN="PRIVATE_TOKEN")
        cases = [
            [],
            ["--list", "extra"],
            ["--pr", "797", "--sha"],
            ["--pr", "797", "--sha", SHA, "extra"],
            ["--sha", "797", "--pr", SHA],
        ]
        cases += [
            ["--pr", number, "--sha", SHA]
            for number in ("0", "-1", "01", "٧٩٧", "797;PRIVATE_TOKEN")
        ]
        cases += [
            ["--pr", "797", "--sha", sha]
            for sha in ("bad", SHA.upper(), SHA + "PRIVATE_TOKEN")
        ]
        for flags in cases:
            code, err, reads, posts = self.invoke(flags, env)
            self.assertEqual((code, reads, posts), (1, 0, 0), flags)
            self.assertIn("arguments", err)
            self.assertNotIn("PRIVATE_TOKEN", err)

    def test_ascii_integer_limit_remains_a_reachable_arguments_guard(self):
        limit = sys.get_int_max_str_digits()
        if limit:
            env = dict(GITHUB_REPOSITORY=REPO, GH_TOKEN="PRIVATE_TOKEN")
            flags = ["--pr", "1" * (limit + 1), "--sha", SHA]
            self.assertEqual(
                self.invoke(flags, env), (1, "codex reconcile: arguments\n", 0, 0)
            )

    def test_missing_token_and_invalid_repository_never_read_or_post(self):
        for env in (
            dict(GITHUB_REPOSITORY=REPO),
            dict(GITHUB_REPOSITORY="owner/..", GH_TOKEN="PRIVATE_TOKEN"),
            dict(GITHUB_REPOSITORY="owner/.", GH_TOKEN="PRIVATE_TOKEN"),
            dict(GH_TOKEN="PRIVATE_TOKEN"),
        ):
            self.assertEqual(
                self.invoke(["--list"], env),
                (1, "codex reconcile: environment\n", 0, 0),
            )

    def test_missing_or_unwritable_output_is_classified_as_output(self):
        with tempfile.TemporaryDirectory() as directory:
            for path in (None, directory):
                env = dict(GITHUB_REPOSITORY=REPO, GH_TOKEN="PRIVATE_TOKEN")
                env.update({"GITHUB_OUTPUT": path} if path is not None else {})
                code, err, _, posts = self.invoke(["--list"], env)
                self.assertEqual((code, posts), (1, 0))
                self.assertEqual(err, "codex reconcile: output\n")

    def test_real_transport_failure_is_sanitized_and_stops_after_one_request(self):
        target = load()
        err = io.StringIO()
        env = dict(GITHUB_REPOSITORY=REPO, GH_TOKEN="PRIVATE_TOKEN")
        failure = subprocess.CalledProcessError(
            1, ["gh", "api"], stderr="PRIVATE_TOKEN"
        )
        with (
            patch.dict(os.environ, env, clear=True),
            patch.object(
                target.events.subprocess, "run", side_effect=failure
            ) as request,
            contextlib.redirect_stderr(err),
        ):
            self.assertEqual(target.main(["--list"]), 1)
        self.assertEqual(request.call_count, 1)
        self.assertEqual(err.getvalue(), "codex reconcile: api\n")

    def test_external_check_states_cannot_veto_a_trusted_pipeline_plan(self):
        for status, conclusion in (("WAITING", None), ("COMPLETED", "FAILURE")):
            server = Server()
            row = schedule.discovery_node(server, server.data["pull"])
            contexts = row["commits"]["nodes"][0]["commit"]["statusCheckRollup"][
                "contexts"
            ]
            contexts["nodes"].append(
                dict(
                    __typename="CheckRun",
                    name="manual deploy",
                    status=status,
                    conclusion=conclusion,
                )
            )
            result = schedule.ScheduledReconciliationTests().invoke(server, [[row]])
            self.assertEqual(result[0], 0, result[2])
            self.assertEqual(json.loads(result[1]), [dict(number=797, sha=SHA)])
            worker = schedule.ScheduledReconciliationTests().invoke(
                server, flags=["--pr", "797", "--sha", SHA]
            )
            self.assertEqual(json.loads(worker[1]), dict(action="merge", job_id=21))
