"""Title events must independently authorize owner requirements.

Source: GitHub Issue.editor describes comment edits; existing vscode issue334398
has a RenamedTitleEvent with editor=null,lastEditedAt=null (2026-10-28 probe).
"""

import copy
import unittest

from test_ci_autopilot_issues import OWNER, authorize, issue


def rename(item, actor=OWNER):
    item["titleEvents"] = {
        "totalCount": 1,
        "pageInfo": {"hasNextPage": False},
        "nodes": [
            {
                "__typename": "RenamedTitleEvent",
                "id": "RTE_fixture",
                "currentTitle": item["title"],
                "actor": copy.deepcopy(actor),
            }
        ],
    }
    return item


class TitleTrust(unittest.TestCase):
    def test_initial_owner_title_and_latest_owner_rename_are_authorized(self):
        self.assertIsNotNone(authorize(issue(), OWNER))
        item = rename(issue())
        self.assertIsNotNone(authorize(item, OWNER))
        item["titleEvents"]["totalCount"] = 2
        self.assertIsNotNone(authorize(item, OWNER))

    def test_foreign_rename_is_rejected_even_while_body_is_pristine(self):
        item = rename(issue(), issue("outsider")["author"])
        self.assertIsNone(item["editor"])
        self.assertIsNone(item["lastEditedAt"])
        self.assertIsNone(authorize(item, OWNER))

    def test_rename_actor_requires_both_owner_login_and_immutable_id(self):
        for actor in ({**OWNER, "id": "U_other"}, {**OWNER, "login": "outsider"}, None):
            with self.subTest(actor=actor):
                self.assertIsNone(authorize(rename(issue(), actor), OWNER))

    def test_missing_incomplete_or_wrong_current_title_evidence_is_rejected(self):
        for corruption in ("missing", "truncated", "currentTitle", "page", "count"):
            item = rename(issue())
            if corruption == "missing":
                item.pop("titleEvents")
            elif corruption == "truncated":
                item["titleEvents"]["nodes"] = []
            elif corruption == "currentTitle":
                item["titleEvents"]["nodes"][0]["currentTitle"] = "another title"
            elif corruption == "page":
                item["titleEvents"]["pageInfo"]["hasNextPage"] = True
            else:
                item["titleEvents"]["totalCount"] = True
            with self.subTest(corruption=corruption):
                self.assertIsNone(authorize(item, OWNER))
