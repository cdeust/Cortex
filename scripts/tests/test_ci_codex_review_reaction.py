"""Contract of the reaction verdict: Codex's thumbs-up closes a null security review.

Since 2026-10-31 Codex posts no no-issues receipt and reacts +1 on the PR once
both reviews finish with no findings (cortex-viz PR216, PR218, PR219, PR220;
Cortex PR838, PR840, PR846, PR847). The receipt keeps precedence; its
`verdict_missing` yields to the reaction when both Completed rows of the summary
name the head, the summary has no finding text, the Codex Bot's +1 is not
earlier than the later row (to the second), no eyes reaction remains and no
native finding thread is unresolved by the owner. Port of cdeust/Cortex PR847.
"""

import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1]
REPO, PR = "owner/project", 216
SHA = "d08360622d35cfbcf137eabfd7620eecce5f5af3"  # cortex-viz PR216 head, 2026-11-03
BOT = "chatgpt-codex-connector[bot]"
# source: Codex summary 6600075171 (Cortex PR848): one table row per review.
CODE_AT, SECURITY_AT = "2026-11-03T11:11:34.103434Z", "2026-11-03T11:12:56.478597Z"
THUMBS_AT = "2026-11-03T11:13:00Z"  # source: cortex-viz PR216 reactions, 2026-11-03


def load():
    """The shared module instances: the reader and the other tests import the same ones."""
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    runtime = importlib.import_module("ci_codex_review_runtime")
    importlib.import_module("ci_codex_review_comments")
    return runtime, importlib.import_module("ci_codex_review_reaction")


def summary(short=SHA[:7], code=CODE_AT, security=SECURITY_AT, extra=""):
    return (
        "<!-- codex-pull-request-review-summary -->\n## Codex Review Summary\n\n"
        "| Review | Status | Commit | Review trigger |\n| --- | --- | --- | --- |\n"
        f'| 📝 **Code Review** | ✅ **Completed** <relative-time datetime="{code}">{code}'
        f"</relative-time> | `{short}` | New commits |\n"
        f'| 🔒 **Security Review** | ✅ **Completed** <relative-time datetime="{security}">'
        f"{security}</relative-time> | `{short}` | New commits |\n" + extra
    )


def review(sha=SHA, any_=None, unresolved=None, status="completed"):
    return dict(commit_sha=sha, status=status, has_any_findings=any_, has_unresolved_findings=unresolved)


def metadata(sha=SHA, status="completed"):
    return dict(repository=REPO, pullRequestNumber=PR, headSha=sha, status=status)


def reaction(content="+1", at=THUMBS_AT, login=BOT):
    # The reactions API reports the Codex Bot with type "User"; only the login is read.
    return {"content": content, "created_at": at, "user": {"login": login, "type": "User"}}


def thread(resolved, resolver=None):
    return {
        "isResolved": resolved,
        "resolvedBy": resolver,
        "comments": {"nodes": [{
            "databaseId": 1,
            "body": "<!-- codex-security-review-finding:v1 -->\nP2",
            "author": {"login": "chatgpt-codex-connector", "__typename": "Bot"},
        }]},
    }


def threads_page(nodes, sha=SHA):
    return {"data": {"repository": {"pullRequest": {
        "headRefOid": sha,
        "reviewThreads": {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": nodes},
    }}}}


class ReactionVerdictTests(unittest.TestCase):
    def setUp(self):
        self.runtime, self.reaction = load()

    def resolve(self, body=None, reactions=(), threads=(), raw=None, rev=None, meta=None):
        runtime, reaction_module = self.runtime, self.reaction
        calls = []

        def api(endpoint, **options):
            calls.append(endpoint)
            if endpoint.endswith("/reactions"):
                return raw if raw is not None else [list(reactions)]
            if endpoint == "graphql":
                return [threads_page(list(threads))]
            raise AssertionError(endpoint)

        with patch.object(runtime, "_api", side_effect=api):
            result = reaction_module.resolve_no_findings(
                (REPO, PR, SHA), summary() if body is None else body,
                review() if rev is None else rev, metadata() if meta is None else meta,
            )
        return result, calls

    def test_thumbs_up_at_or_after_the_later_row_is_the_verdict(self):
        for at in (THUMBS_AT, "2026-11-03T11:12:56Z", "2026-11-04T00:00:00Z"):
            with self.subTest(at=at):
                result, calls = self.resolve(reactions=[reaction(at=at)])
                self.assertEqual(result["state"], "success")
                self.assertEqual(result["source"], "github_reaction")
                self.assertEqual(result["reacted_at"], at)
                self.assertEqual(calls, [f"repos/{REPO}/issues/{PR}/reactions", "graphql"])

    def test_thumbs_up_one_second_before_the_security_row_is_stale(self):
        result, _ = self.resolve(reactions=[reaction(at="2026-11-03T11:12:55Z")])
        self.assertIsNone(result)

    def test_eyes_means_a_review_is_still_running(self):
        result, _ = self.resolve(reactions=[reaction(), reaction("eyes", "2026-11-03T11:10:00Z")])
        self.assertIsNone(result)

    def test_no_thumbs_up_from_the_codex_bot_proves_nothing(self):
        for reactions in ([], [reaction(login="someone")], [reaction("heart")]):
            with self.subTest(reactions=reactions):
                self.assertIsNone(self.resolve(reactions=reactions)[0])

    def test_rows_for_another_head_never_read_the_api(self):
        result, calls = self.resolve(body=summary(short="1234567"), reactions=[reaction()])
        self.assertIsNone(result)
        self.assertEqual(calls, [])

    def test_one_row_or_a_duplicated_row_is_not_a_completed_pair(self):
        one = summary().replace("| 📝 **Code Review**", "| 📝 Code Review")
        twice = summary() + summary().splitlines()[-1] + "\n"
        for body in (one, twice):
            with self.subTest(body=body[:40]):
                result, calls = self.resolve(body=body, reactions=[reaction()])
                self.assertIsNone(result)
                self.assertEqual(calls, [])

    def test_finding_text_in_the_summary_voids_the_clean_path(self):
        for text in ("\n### Security findings\n", "<!-- codex-security-review-finding:v1 -->"):
            with self.subTest(text=text):
                result, calls = self.resolve(body=summary(extra=text), reactions=[reaction()])
                self.assertIsNone(result)
                self.assertEqual(calls, [])

    def test_explicit_flags_or_another_head_in_the_metadata_are_not_this_path(self):
        cases = (
            dict(rev=review(any_=False, unresolved=False)),
            dict(rev=review(any_=True)),
            dict(rev=review(status="running")),
            dict(rev=review(sha="1" * 40)),
            dict(meta=metadata(sha="1" * 40)),
            dict(meta=metadata(status="running")),
            dict(meta=None),
        )
        for case in cases:
            with self.subTest(case=case):
                kwargs = dict(reactions=[reaction()])
                if "meta" in case and case["meta"] is None:
                    kwargs["meta"] = {}
                else:
                    kwargs.update(case)
                result, calls = self.resolve(**kwargs)
                self.assertIsNone(result)
                self.assertEqual(calls, [])

    def test_an_unresolved_or_foreign_resolved_thread_keeps_the_verdict_open(self):
        for node in (thread(False), thread(True, {"login": "someone", "__typename": "User"})):
            with self.subTest(node=node):
                self.assertIsNone(self.resolve(reactions=[reaction()], threads=[node])[0])

    def test_a_thread_resolved_by_the_owner_does_not_block(self):
        owner = {"login": REPO.split("/")[0], "__typename": "User"}
        result, _ = self.resolve(reactions=[reaction()], threads=[thread(True, owner)])
        self.assertEqual(result["state"], "success")

    def test_malformed_reaction_payloads_are_protocol_errors(self):
        runtime = self.runtime
        for raw in ({"content": "+1"}, [{"content": "+1"}], [[{"content": 1, "user": {}}]],
                    [[{"content": "+1", "user": {"login": 5}}]], [[{"content": "+1", "user": {"login": BOT}}]]):
            with self.subTest(raw=raw):
                with self.assertRaises(runtime.EvidenceError) as caught:
                    self.resolve(raw=raw)
                self.assertEqual(str(caught.exception), "protocol")

    def test_malformed_stamps_are_protocol_errors(self):
        runtime = self.runtime
        for at in (None, 1, "2026-11-03 11:13:00Z", "2026-11-03T11:13:00+00:00", "2026-13-03T11:13:00Z"):
            with self.subTest(at=at):
                with self.assertRaises(runtime.EvidenceError):
                    self.resolve(reactions=[reaction(at=at)])
        with self.assertRaises(runtime.EvidenceError):
            self.resolve(body=summary(security="2026-13-03T11:12:56.1Z"), reactions=[reaction()])

    def test_a_repository_without_one_slash_is_a_protocol_error(self):
        runtime, reaction_module = self.runtime, self.reaction
        with patch.object(runtime, "_api", return_value=[[reaction()]]):
            with self.assertRaises(runtime.EvidenceError):
                reaction_module.resolve_no_findings(
                    ("owner", PR, SHA), summary(),
                    review(), dict(repository="owner", pullRequestNumber=PR, headSha=SHA, status="completed"),
                )

    def test_reaction_verdict_only_replaces_a_missing_receipt(self):
        runtime, reaction_module = self.runtime, self.reaction
        receipt_ok = {"state": "success", "source": "codex_security_receipt"}
        with patch.object(runtime, "_api", side_effect=AssertionError("never read")):
            self.assertIsNone(reaction_module.reaction_verdict(None, (REPO, PR, SHA), summary(), review(), metadata()))
            self.assertIs(reaction_module.reaction_verdict(receipt_ok, (REPO, PR, SHA), summary(), review(), metadata()), receipt_ok)
        missing = {"state": "verdict_missing", "source": "codex_security_receipt", "receipt_ids": []}
        with patch.object(runtime, "_api", side_effect=lambda endpoint, **_: [[reaction()]] if endpoint.endswith("/reactions") else [threads_page([])]):
            result = reaction_module.reaction_verdict(missing, (REPO, PR, SHA), summary(), review(), metadata())
        self.assertEqual(result["source"], "github_reaction")
        with patch.object(runtime, "_api", side_effect=lambda endpoint, **_: [[]] if endpoint.endswith("/reactions") else [threads_page([])]):
            self.assertIs(reaction_module.reaction_verdict(missing, (REPO, PR, SHA), summary(), review(), metadata()), missing)


if __name__ == "__main__":
    unittest.main()
