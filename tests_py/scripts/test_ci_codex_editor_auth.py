"""P1 finding4395607291: the immutable editor must authenticate the same body.

Actor fixture: native comment6456275844, queried through IssueComment on2026-10-28.
"""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

READER = Path(__file__).resolve().parents[2] / "scripts/ci_codex_reviews.py"
SHA, REPO, PR = "a" * 40, "owner/project", 464
BOT_ID = "BOT_kgDOC98s_g"


def reader():
    spec = importlib.util.spec_from_file_location("codex_editor_reader", READER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def comment(identity=1, stamp="2026-10-28T00:11:18Z"):
    review = dict(
        commit_sha=SHA,
        status="completed",
        has_any_findings=False,
        has_unresolved_findings=False,
    )
    body = (
        "<!-- codex-pull-request-review-summary -->\n"
        "<!-- codex-review-state:v1 "
        + json.dumps(dict(code_review=review, security_review=review))
        + " -->"
    )
    return dict(
        id=identity,
        updated_at=stamp,
        body=body,
        editor=None,
        lastEditedAt=None,
        user=dict(login="chatgpt-codex-connector[bot]", type="Bot", node_id=BOT_ID),
    )


def bot_editor():
    return dict(login="chatgpt-codex-connector", __typename="Bot", id=BOT_ID)


def page(rows, more=False, cursor=None):
    nodes = [
        dict(
            databaseId=row["id"],
            body=row["body"],
            updatedAt=row["updated_at"],
            author=dict(
                login="chatgpt-codex-connector",
                __typename="Bot",
                id=row["user"]["node_id"],
            ),
            editor=row["editor"],
            lastEditedAt=row["lastEditedAt"],
        )
        for row in rows
    ]
    return {
        "data": {
            "repository": {
                "pullRequest": {
                    "number": PR,
                    "headRefOid": SHA,
                    "comments": {
                        "nodes": nodes,
                        "pageInfo": {
                            "hasNextPage": more,
                            "endCursor": cursor,
                        },
                    },
                }
            }
        }
    }


class SummaryEditorTests(unittest.TestCase):
    def evaluate(self, rows):
        return reader().review_evidence(rows, SHA, REPO, PR)

    def test_pristine_and_native_bot_edits_are_accepted(self):
        for editor, stamp in ((None, None), (bot_editor(), "2026-10-28T00:11:17Z")):
            row = comment()
            row.update(editor=editor, lastEditedAt=stamp)
            with self.subTest(editor=editor):
                self.assertEqual(self.evaluate([row])["state"], "success")

    def test_human_edit_cannot_forge_a_clean_native_summary(self):
        row = comment()
        row.update(
            editor=dict(login="writer", __typename="User", id="USER_fixture"),
            lastEditedAt="2026-10-28T00:11:18Z",
        )
        result = self.evaluate([row])
        self.assertEqual((result["state"], result["reason"]), ("blocked", "editor"))
        self.assertFalse(result["reviews_complete"])

    def test_bot_login_does_not_substitute_for_matching_immutable_identity(self):
        for field, value in (
            ("id", "OTHER_BOT"),
            ("login", "other-bot"),
            ("__typename", "User"),
        ):
            row = comment()
            editor = bot_editor()
            editor[field] = value
            row.update(editor=editor, lastEditedAt="2026-10-28T00:11:18Z")
            with self.subTest(field=field):
                self.assertEqual(self.evaluate([row])["state"], "blocked")

    def test_missing_or_inconsistent_edit_attestation_fails_closed(self):
        cases = []
        for missing in ("editor", "lastEditedAt"):
            row = comment()
            del row[missing]
            cases.append(row)
        row = comment()
        row["user"].pop("node_id")
        cases.append(row)
        for editor, stamp in (
            (None, "2026-10-28T00:11:18Z"),
            (bot_editor(), None),
            (bot_editor(), "2026-99-99T00:11:18Z"),
            (bot_editor(), True),
        ):
            row = comment()
            row.update(editor=editor, lastEditedAt=stamp)
            cases.append(row)
        for row in cases:
            with self.subTest(row=row):
                self.assertEqual(self.evaluate([row])["state"], "blocked")

    def test_newest_tampered_summary_never_falls_back_to_an_older_clean_one(self):
        row = comment(2, "2026-10-28T00:12:18Z")
        row.update(
            editor=dict(login="writer", __typename="User", id="USER_fixture"),
            lastEditedAt="2026-10-28T00:12:18Z",
        )
        self.assertEqual(self.evaluate([comment(), row])["state"], "blocked")
        row["body"] = "marker removed by the last editor"
        self.assertEqual(self.evaluate([comment(), row])["state"], "blocked")

    def test_trusted_non_summary_bot_comments_keep_the_previous_behavior(self):
        row = comment(2, "2026-10-28T00:12:18Z")
        row["body"] = "ordinary native bot message"
        self.assertEqual(self.evaluate([comment(), row])["state"], "success")
        row.update(editor=bot_editor(), lastEditedAt="2026-10-28T00:12:18Z")
        self.assertEqual(self.evaluate([comment(), row])["state"], "success")


class SummaryGraphQLTests(unittest.TestCase):
    def test_event_proof_uses_the_same_editor_authenticated_graphql_body(self):
        path = READER.with_name("ci_codex_review_event.py")
        spec = importlib.util.spec_from_file_location("codex_editor_event", path)
        event = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(event)
        row = comment()
        row.update(
            editor=dict(login="writer", __typename="User", id="USER_fixture"),
            lastEditedAt="2026-10-28T00:11:18Z",
        )
        with patch.object(event.source, "_api", return_value=[page([row])]) as request:
            result = event._proof(REPO, PR, {"head_sha": SHA}, [])
        self.assertEqual((result["state"], result["reason"]), ("blocked", "editor"))
        self.assertFalse(result["reviews_complete"])
        self.assertEqual(request.call_args.args, ("graphql",))

    def test_fetch_reads_body_and_editor_together_with_live_head_checks(self):
        module = reader()
        pull = dict(
            state="open",
            draft=False,
            head=dict(sha=SHA, repo=dict(full_name=REPO)),
            base=dict(ref="main", repo=dict(full_name=REPO)),
        )
        replies = [pull, [page([comment()])], pull]
        with patch.object(module, "_api", side_effect=replies) as request:
            result = module._fetch(SimpleNamespace(repo=REPO, pr=PR, sha=SHA))
        self.assertEqual(result["state"], "success")
        self.assertEqual(request.call_count, 3)
        graph = request.call_args_list[1]
        self.assertEqual(graph.args, ("graphql",))
        self.assertTrue(graph.kwargs["paginate"])
        query = graph.kwargs["fields"]["query"]
        for field in ("body", "editor", "lastEditedAt", "... on Bot { id }"):
            self.assertIn(field, query)

    def test_pagination_is_complete_and_keeps_same_node_body_attestation(self):
        module = reader()
        first = page([comment()], True, "cursor1")
        second = page([comment(2, "2026-10-28T00:12:18Z")])
        rows = module.runtime._comment_pages([first, second], SHA, PR)
        self.assertEqual([row["id"] for row in rows], [1, 2])
        second["data"]["repository"]["pullRequest"]["comments"]["nodes"][0][
            "editor"
        ] = {
            "login": "writer",
            "__typename": "User",
            "id": "USER_fixture",
        }
        rows = module.runtime._comment_pages([first, second], SHA, PR)
        self.assertEqual(
            module.review_evidence(rows, SHA, REPO, PR)["state"], "blocked"
        )

    def test_graphql_errors_incomplete_pages_and_missing_fields_fail_closed(self):
        module = reader()
        cases = [
            None,
            [],
            [dict(errors=[dict(message="partial")])],
            [page([comment()], True, "cursor1")],
        ]
        malformed = page([comment()])
        malformed["data"]["repository"]["pullRequest"]["comments"]["nodes"][0].pop(
            "editor"
        )
        cases.append([malformed])
        cases.append([page([comment(), comment()])])
        for pages in cases:
            with self.subTest(pages=pages), self.assertRaises(ValueError):
                module.runtime._comment_pages(pages, SHA, PR)

    def test_moved_head_and_wrong_pr_fail_closed(self):
        module = reader()
        for field, value in (("headRefOid", "b" * 40), ("number", PR + 1)):
            packet = page([comment()])
            packet["data"]["repository"]["pullRequest"][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                module.runtime._comment_pages([packet], SHA, PR)
