"""The post-merge engine closes the issues a resolver-merged PR names.

GitHub ignores closing keywords when the merge is made with the workflow's
GITHUB_TOKEN: the 8 resolver merges with `Closes #N` before 2026-11-06 left every
issue open (#801 after #908), while merges by a person closed theirs within minutes.
The `close-issues` job closes what GitHub links to the PR. Its script is run here
against a fake API that records each call.
"""

from pathlib import Path
import re
import textwrap
import unittest
import unittest.mock

ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / ".github/workflows/pipeline-post-merge.yml"
REPO = "cdeust/Cortex"


def closer(responses):
    """The job's script, with `call` replaced by a recorder serving `responses`."""
    text = ENGINE.read_text(encoding="utf-8")
    source = text.split("python3 - <<'CLOSE'\n", 1)[1].split("\n          CLOSE", 1)[0]
    namespace = {"__name__": "close_issues_test"}
    exec(compile(textwrap.dedent(source), "close_issues", "exec"), namespace)
    calls = []

    def call(method, url, payload=None):
        calls.append((method, url, payload))
        return responses.get((method, url.rsplit("/", 1)[-1]), {})

    namespace["call"] = call
    return namespace, calls


def graphql(merged, issues):
    nodes = [{"number": n, "state": state} for n, state in issues]
    pull = {"merged": merged, "closingIssuesReferences": {"nodes": nodes}}
    return {("POST", "graphql"): {"data": {"repository": {"pullRequest": pull}}}}


class CloseIssuesTests(unittest.TestCase):
    def run_main(self, responses):
        ns, calls = closer(responses)
        env = {"GITHUB_REPOSITORY": REPO, "PR_NUMBER": "908", "GH_TOKEN": "t"}
        with unittest.mock.patch.dict("os.environ", env):
            ns["main"]()
        return calls

    def test_each_open_linked_issue_is_commented_then_closed(self):
        calls = self.run_main(graphql(True, [(801, "OPEN")]))
        writes = [
            (m, u.removeprefix("https://api.github.com"), p) for m, u, p in calls[1:]
        ]
        self.assertEqual(writes[0][:2], ("POST", f"/repos/{REPO}/issues/801/comments"))
        self.assertIn("Closed by #908", writes[0][2]["body"])
        self.assertEqual(
            writes[1],
            (
                "PATCH",
                f"/repos/{REPO}/issues/801",
                {"state": "closed", "state_reason": "completed"},
            ),
        )

    def test_an_issue_already_closed_is_left_alone(self):
        calls = self.run_main(graphql(True, [(801, "CLOSED")]))
        self.assertEqual([m for m, _, _ in calls], ["POST"])  # the query only

    def test_a_pr_that_is_not_merged_stops_the_job(self):
        with self.assertRaises(SystemExit):
            self.run_main(graphql(False, [(801, "OPEN")]))

    def test_graphql_errors_stop_the_job(self):
        with self.assertRaises(SystemExit):
            self.run_main({("POST", "graphql"): {"errors": [{"message": "nope"}]}})


class JobContractTests(unittest.TestCase):
    def job(self):
        text = ENGINE.read_text(encoding="utf-8")
        return re.search(
            r"\n  close-issues:\n(.*?)\n  # ci\.json first", text, re.S
        ).group(1)

    def test_the_job_runs_after_a_successful_resolve_only(self):
        body = self.job()
        self.assertIn("needs: resolve", body)
        self.assertIn("needs.resolve.result == 'success'", body)

    def test_the_job_can_write_issues_and_nothing_else(self):
        permissions = re.search(r"permissions:\n((?:      \S.*\n)+)", self.job()).group(
            1
        )
        self.assertEqual(
            permissions.split(), ["issues:", "write", "pull-requests:", "read"]
        )

    def test_the_resolver_exposes_the_merged_pr_number(self):
        text = ENGINE.read_text(encoding="utf-8")
        self.assertIn("pr_number: ${{ steps.resolve.outputs.pr_number }}", text)


if __name__ == "__main__":
    unittest.main()
