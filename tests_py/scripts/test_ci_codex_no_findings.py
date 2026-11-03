"""Completed Codex security review with both verdict flags null (PR833, PR846).

Source: PR846 summary comment 6591745340 on e8ab290 (security_review completed,
has_any_findings null, has_unresolved_findings null) and the Codex +1 reaction
on the PR at 2026-11-03T00:23:49Z, after the head commit of 2026-11-03T00:22:08Z.
Without this path the reader reported "pending" for ever and the Pipeline's merge
job kept the name "merge pending review", which branch protection never accepts.
"""

import json
import unittest
from unittest.mock import patch

from tests_py.scripts.test_ci_codex_reviews import SHA, OTHER, comment, module, state

REPO, PR = "cdeust/Cortex", 846
COMMITTED = "2026-11-03T00:22:08Z"
REACTED = "2026-11-03T00:23:49Z"
CODEX = {"login": "chatgpt-codex-connector[bot]", "type": "Bot"}


def summary(sha=SHA, metadata_sha=SHA):
    data = state(sha)
    data["security_review"].update(has_any_findings=None, has_unresolved_findings=None)
    row = comment(data)
    metadata = dict(
        repository=REPO, pullRequestNumber=PR, headSha=metadata_sha, status="completed"
    )
    row["body"] += "\n<!-- codex-security-review:v1 " + json.dumps(metadata) + " -->"
    row["body"] += "\n<details>About Codex</details>"
    return row


def reaction(content="+1", user=CODEX, created=REACTED):
    return {"content": content, "user": dict(user), "created_at": created}


def commit(date=COMMITTED):
    return {"sha": SHA, "commit": {"committer": {"date": date}}}


def api(reactions, head=None):
    def request(endpoint, *, paginate=False, fields=None):
        if endpoint.endswith("/reactions"):
            assert paginate
            return [list(reactions)]
        assert endpoint == f"repos/{REPO}/commits/{SHA}" and not paginate
        return commit() if head is None else head

    return request


class CodexNoFindingsTests(unittest.TestCase):
    def evaluate(self, reactions, row=None, head=None):
        m = module()
        with patch.object(m.runtime, "_api", side_effect=api(reactions, head)):
            return m.review_evidence([summary() if row is None else row], SHA, REPO, PR)

    def test_codex_plus_one_after_the_reviewed_commit_completes_the_review(self):
        result = self.evaluate([reaction()])
        self.assertEqual(result["state"], "success")
        self.assertEqual(result["reason"], "reviews_complete")
        self.assertTrue(result["reviews_complete"])
        resolution = result["security_review"]["resolution"]
        self.assertEqual(resolution["source"], "github_reaction")
        self.assertEqual(resolution["reacted_at"], REACTED)
        self.assertIsNone(result["security_review"]["has_any_findings"])

    def test_no_reaction_other_user_or_eyes_keeps_the_review_pending(self):
        other = {"login": "cdeust", "type": "User"}
        for reactions in (
            [],
            [reaction(user=other)],
            [reaction("heart")],
            [reaction(), reaction("eyes")],
        ):
            result = self.evaluate(reactions)
            self.assertEqual(result["state"], "pending", reactions)
            self.assertFalse(result["reviews_complete"])

    def test_a_plus_one_older_than_the_reviewed_commit_is_stale(self):
        for created in ("2026-11-03T00:22:08Z", "2026-11-02T23:59:59Z"):
            result = self.evaluate([reaction(created=created)])
            self.assertEqual(result["state"], "pending", created)

    def test_running_stale_or_mismatched_metadata_never_reads_reactions(self):
        rows = [summary(metadata_sha=OTHER)]
        for field, value in (("status", "running"), ("commit_sha", OTHER)):
            row = summary()
            data = state()
            data["security_review"].update(
                has_any_findings=None, has_unresolved_findings=None
            )
            data["security_review"][field] = value
            old = row["body"].split("<!-- codex-review-state:v1 ", 1)[1]
            row["body"] = row["body"].replace(old.split(" -->", 1)[0], json.dumps(data))
            rows.append(row)
        for row in rows:
            m = module()
            with patch.object(
                m.runtime, "_api", side_effect=AssertionError("unexpected API")
            ):
                result = m.review_evidence([row], SHA, REPO, PR)
            self.assertNotEqual(result["state"], "success")

    def test_without_repository_context_the_null_verdict_stays_pending(self):
        m = module()
        with patch.object(m.runtime, "_api", side_effect=AssertionError("unexpected")):
            self.assertEqual(m.review_evidence([summary()], SHA)["state"], "pending")

    def test_malformed_reaction_or_commit_records_block_without_a_verdict(self):
        anonymous = self.evaluate([{"content": "+1", "created_at": REACTED}])
        self.assertEqual(anonymous["state"], "pending")
        for reactions, head in (
            ([{"user": dict(CODEX), "created_at": REACTED}], None),
            ([{"user": dict(CODEX), "content": "+1"}], None),
            ([reaction()], {"sha": SHA, "commit": {}}),
        ):
            result = self.evaluate(reactions, head=head)
            self.assertEqual(result["state"], "blocked", (reactions, head))
            self.assertEqual(result["reason"], "protocol")
            self.assertFalse(result["reviews_complete"])

    def test_api_failure_blocks_without_inventing_a_verdict(self):
        m = module()
        with patch.object(
            m.runtime, "_api", side_effect=m.runtime.EvidenceError("api")
        ):
            result = m.review_evidence([summary()], SHA, REPO, PR)
        self.assertEqual(result["state"], "blocked")
        self.assertEqual(result["reason"], "api")
        self.assertFalse(result["reviews_complete"])

    def test_explicit_false_verdicts_do_not_consult_reactions(self):
        m = module()
        with patch.object(m.runtime, "_api", side_effect=AssertionError("unexpected")):
            result = m.review_evidence([comment()], SHA, REPO, PR)
        self.assertEqual(result["state"], "success")
