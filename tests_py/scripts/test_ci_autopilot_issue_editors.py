"""Public GitHub editor metadata must authenticate every owner requirement."""

import copy
import unittest

from test_ci_autopilot_issues import OWNER, authorize, comment, fingerprint, issue


class LastEditorTrust(unittest.TestCase):
    def test_foreign_edit_of_owner_discussion_cannot_supply_requirements(self):
        item = issue()
        row = comment("owner", "forged requirements")
        row.update(
            editor=issue("outsider")["author"], lastEditedAt="2026-10-28T00:00:00Z"
        )
        item["comments"] = [row]
        self.assertIsNone(authorize(item, OWNER))

    def test_foreign_edit_of_owner_approval_cannot_authorize_an_issue(self):
        item = issue("outsider")
        snapshot = {key: item[key] for key in ("number", "title", "body", "comments")}
        marker = (
            "<!-- cortex-autopilot:approve sha256=" + fingerprint(snapshot) + " -->"
        )
        row = comment("owner", marker)
        row.update(
            editor=issue("outsider")["author"], lastEditedAt="2026-10-28T00:00:00Z"
        )
        item["comments"] = [row]
        self.assertIsNone(authorize(item, OWNER))

    def test_owner_edits_are_accepted_only_with_matching_immutable_id(self):
        for target in ("issue", "comment"):
            with self.subTest(target=target):
                item = issue()
                row = item if target == "issue" else comment("owner", "requirements")
                if target == "comment":
                    item["comments"] = [row]
                row.update(
                    editor=copy.deepcopy(OWNER), lastEditedAt="2026-10-28T00:00:00Z"
                )
                self.assertIsNotNone(authorize(item, OWNER))
                row["editor"]["id"] = "U_other"
                self.assertIsNone(authorize(item, OWNER))

    def test_missing_or_inconsistent_metadata_never_auto_authorizes(self):
        for target in ("issue", "comment"):
            for field in ("editor", "lastEditedAt", "author"):
                with self.subTest(target=target, field=field):
                    item = issue()
                    row = (
                        item if target == "issue" else comment("owner", "requirements")
                    )
                    if target == "comment":
                        item["comments"] = [row]
                    row.pop(field)
                    self.assertIsNone(authorize(item, OWNER))
        item = issue()
        item["lastEditedAt"] = "2026-10-28T00:00:00Z"
        self.assertIsNone(authorize(item, OWNER))
        item = issue()
        item["author"]["id"] = "U_spoof"
        self.assertIsNone(authorize(item, OWNER))

    def test_unknown_editor_identity_or_invalid_edit_timestamp_is_rejected(self):
        for editor, stamp in (
            (OWNER, None),
            (None, "2026-10-28T00:00:00Z"),
            (OWNER, "not-a-date"),
            (OWNER, "2026-10-28"),
            ({"login": "owner", "__typename": "User"}, "2026-10-28T00:00:00Z"),
            ({**OWNER, "__typename": "Bot"}, "2026-10-28T00:00:00Z"),
        ):
            with self.subTest(editor=editor, stamp=stamp):
                item = issue()
                item.update(editor=editor, lastEditedAt=stamp)
                self.assertIsNone(authorize(item, OWNER))

    def test_deleted_foreign_author_cannot_block_an_owner_issue(self):
        original = authorize(issue(), OWNER)
        changed = issue()
        row = comment("outsider", "irrelevant foreign discussion")
        row["author"] = None
        changed["comments"] = [row]
        self.assertEqual(authorize(changed, OWNER), original)
