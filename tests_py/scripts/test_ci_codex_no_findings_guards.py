"""Guards of the null-verdict reaction path: each test fails if its guard is removed.

Source: Claude review on PR847 (head 051f764), which showed that dropping the
security-only guard or the fully-null guard left every existing test green.
"""

import json
import unittest
from unittest.mock import patch

from tests_py.scripts.test_ci_codex_no_findings import (
    CODE_DONE,
    CODEX,
    PR,
    REPO,
    SECURITY_DONE,
    CodexNoFindingsTests,
    reaction,
    row_text,
    summary,
)
from tests_py.scripts.test_ci_codex_reviews import SHA, module, state


class CodexNoFindingsGuardTests(unittest.TestCase):
    evaluate = CodexNoFindingsTests.evaluate

    def test_only_a_fully_null_security_verdict_takes_the_reaction_path(self):
        for flags in ((None, True), (None, False), (False, None), (True, None)):
            row = summary()
            data = state()
            data["security_review"].update(
                has_any_findings=flags[0], has_unresolved_findings=flags[1]
            )
            marker = row["body"].split("<!-- codex-review-state:v1 ", 1)[1]
            row["body"] = row["body"].replace(
                marker.split(" -->", 1)[0], json.dumps(data)
            )
            m = module()
            with patch.object(
                m.runtime, "_api", side_effect=AssertionError("unexpected")
            ):
                result = m.review_evidence([row], SHA, REPO, PR)
            self.assertNotEqual(result["state"], "success", flags)

    def test_a_null_code_review_never_takes_the_reaction_path(self):
        data = state()
        data["code_review"].update(has_any_findings=None, has_unresolved_findings=None)
        row = summary()
        marker = row["body"].split("<!-- codex-review-state:v1 ", 1)[1]
        row["body"] = row["body"].replace(marker.split(" -->", 1)[0], json.dumps(data))
        result = self.evaluate([reaction()], row=row)
        self.assertEqual(result["state"], "pending")
        self.assertFalse(result["reviews_complete"])

    def test_reaction_pages_and_bystander_reactions(self):
        other = {"login": "cdeust", "type": "User"}
        self.assertEqual(
            self.evaluate([[], [reaction()]], raw=True)["state"], "success"
        )
        split = self.evaluate([[reaction()], [reaction("eyes")]], raw=True)
        self.assertEqual(split["state"], "pending")
        bystander = self.evaluate([reaction(), reaction("eyes", user=other)])
        self.assertEqual(bystander["state"], "success")
        user_typed = self.evaluate(
            [reaction(user={"login": CODEX["login"], "type": "User"})]
        )
        self.assertEqual(user_typed["state"], "success")

    def test_the_later_row_sets_the_threshold_whichever_kind_it_is(self):
        rows = (
            row_text("📝 **Code Review**", "2026-11-03T00:23:50.000000Z"),
            row_text("🔒 **Security Review**", SECURITY_DONE),
        )
        result = self.evaluate([reaction()], row=summary(rows=rows))
        self.assertEqual(result["state"], "pending")

    def test_a_malformed_row_is_protocol_before_any_api_call(self):
        rows = (
            row_text("📝 **Code Review**", CODE_DONE),
            row_text("🔒 **Security Review**", "2026-02-30T00:00:00Z"),
        )
        m = module()
        with patch.object(
            m.runtime, "_api", side_effect=m.runtime.EvidenceError("api")
        ):
            result = m.review_evidence([summary(rows=rows)], SHA, REPO, PR)
        self.assertEqual(result["reason"], "protocol")
