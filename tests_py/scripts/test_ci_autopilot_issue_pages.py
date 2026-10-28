"""Issue comment pagination retains same-node editor and owner provenance."""

import copy
from types import SimpleNamespace
import unittest

from test_ci_autopilot_issues import OWNER, comment, issue
from ci_autopilot_issues import intake


def connection(rows, more=False):
    return {
        "totalCount": 2,
        "nodes": rows,
        "pageInfo": {"hasNextPage": more, "endCursor": "cursor1" if more else None},
    }


def pages():
    item = issue()
    item["labels"] = {"nodes": []}
    item["comments"] = connection([comment("owner", "first")], True)
    initial = {
        "data": {
            "repository": {
                "owner": OWNER,
                "issues": {
                    "nodes": [item],
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                },
            }
        }
    }
    following = copy.deepcopy(item)
    row = comment("owner", "second")
    row["databaseId"] = 2
    following["comments"] = connection([row])
    return initial, {"data": {"repository": {"issue": following}}}


class IssuePages(unittest.TestCase):
    def call(self, initial, following):
        calls = []

        def github(options, *args):
            calls.append(args)
            self.assertIn("graphql", args)
            self.assertIn(
                "lastEditedAt", next(x for x in args if x.startswith("query="))
            )
            return following if any(x.startswith("number=") for x in args) else initial

        result = intake(SimpleNamespace(repository="owner/repo"), github)
        return result, calls

    def test_all_graphql_comment_pages_preserve_authenticated_owner_requirements(self):
        initial, following = pages()
        result, calls = self.call(initial, following)
        self.assertEqual(len(result[0]["snapshot"]["comments"]), 2)
        self.assertEqual(len(calls), 2)

    def test_foreign_editor_on_later_page_cannot_supply_owner_requirements(self):
        initial, following = pages()
        row = following["data"]["repository"]["issue"]["comments"]["nodes"][0]
        row.update(
            editor=issue("outsider")["author"], lastEditedAt="2026-10-28T00:00:00Z"
        )
        self.assertEqual(self.call(initial, following)[0], [])

    def test_changed_issue_or_count_or_graphql_error_fails_closed(self):
        for corruption in ("body", "count", "errors", "cursor", "owner", "duplicate"):
            initial, following = pages()
            node = following["data"]["repository"]["issue"]
            if corruption == "body":
                node["body"] += "changed"
            elif corruption == "count":
                node["comments"]["totalCount"] += 1
            elif corruption == "errors":
                following["errors"] = [{"message": "partial response"}]
            elif corruption == "duplicate":
                node["comments"]["nodes"][0]["databaseId"] = 1
            elif corruption == "owner":
                initial["data"]["repository"]["owner"] = {**OWNER, "id": ""}
            else:
                node["comments"]["pageInfo"] = {
                    "hasNextPage": True,
                    "endCursor": "cursor1",
                }
            with self.subTest(corruption=corruption), self.assertRaises(RuntimeError):
                self.call(initial, following)

    def test_issue_cursor_is_separate_from_nested_comment_cursor(self):
        initial, _ = pages()
        first = initial["data"]["repository"]
        item = first["issues"]["nodes"][0]
        item["comments"] = connection(
            [comment("owner", "one"), {**comment("owner", "two"), "databaseId": 2}]
        )
        first["issues"]["pageInfo"] = {"hasNextPage": True, "endCursor": "issue-page2"}
        second = copy.deepcopy(initial)
        second["data"]["repository"]["issues"]["nodes"][0]["number"] = 2
        second["data"]["repository"]["issues"]["pageInfo"] = {
            "hasNextPage": False,
            "endCursor": None,
        }
        calls = []

        def github(options, *args):
            calls.append(args)
            self.assertNotIn("--paginate", args)
            return second if "endCursor=issue-page2" in args else initial

        result = intake(SimpleNamespace(repository="owner/repo"), github)
        self.assertEqual([row["number"] for row in result], [1, 2])
        self.assertEqual(len(calls), 2)
