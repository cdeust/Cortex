"""Completed Codex security review with both verdict flags null (PR833, PR846).

Source: PR846 summary comment 6591745340 on e8ab290 (security_review completed,
has_any_findings null, has_unresolved_findings null; Code Review completed
2026-11-03T00:23:14.923148Z, Security Review completed 00:23:45.383348Z) and the
Codex +1 reaction on the PR at 00:23:49Z. Without this path the reader reported
"pending" for ever and the Pipeline's merge job kept the name "merge pending
review", which branch protection never accepts. Freshness is anchored on the
summary's own completion rows: a commit date would let a later push of an older
commit reuse a stale +1 (PR847 Codex review).
"""

import json
import unittest
from unittest.mock import patch

from tests_py.scripts.test_ci_codex_resolution import page
from tests_py.scripts.test_ci_codex_reviews import SHA, OTHER, comment, module, state

REPO, PR = "cdeust/Cortex", 846
CODE_DONE = "2026-11-03T00:23:14.923148Z"
SECURITY_DONE = "2026-11-03T00:23:45.383348Z"
REACTED = "2026-11-03T00:23:49Z"
CODEX = {"login": "chatgpt-codex-connector[bot]", "type": "Bot"}


def row_text(kind, done, short=SHA[:7]):
    return (
        f"| {kind} | ✅ **Completed** "
        f'<relative-time datetime="{done}">{done}</relative-time> | `{short}` | x |'
    )


def threads(nodes=()):
    packet = page()
    packet["data"]["repository"]["pullRequest"]["reviewThreads"]["nodes"] = list(nodes)
    return [packet]


def summary(sha=SHA, metadata_sha=SHA, rows=None):
    data = state(sha)
    data["security_review"].update(has_any_findings=None, has_unresolved_findings=None)
    row = comment(data)
    metadata = dict(
        repository=REPO, pullRequestNumber=PR, headSha=metadata_sha, status="completed"
    )
    row["body"] += "\n<!-- codex-security-review:v1 " + json.dumps(metadata) + " -->"
    if rows is None:
        rows = (
            row_text("📝 **Code Review**", CODE_DONE),
            row_text("🔒 **Security Review**", SECURITY_DONE),
        )
    row["body"] += "\n## Codex Review Summary\n\n" + "\n".join(rows)
    row["body"] += "\n<details>About Codex</details>"
    return row


def reaction(content="+1", user=CODEX, created=REACTED):
    return {"content": content, "user": dict(user), "created_at": created}


def api(reactions, thread_pages=None, raw=False):
    def request(endpoint, *, paginate=False, fields=None):
        if endpoint == "graphql":
            assert paginate and "reviewThreads" in fields["query"]
            return threads() if thread_pages is None else thread_pages
        assert endpoint == f"repos/{REPO}/issues/{PR}/reactions" and paginate
        return reactions if raw else [list(reactions)]

    return request


class CodexNoFindingsTests(unittest.TestCase):
    def evaluate(self, reactions, row=None, thread_pages=None, raw=False):
        m = module()
        with patch.object(
            m.runtime, "_api", side_effect=api(reactions, thread_pages, raw)
        ):
            return m.review_evidence([summary() if row is None else row], SHA, REPO, PR)

    def test_codex_plus_one_after_the_reviewed_commit_completes_the_review(self):
        result = self.evaluate([reaction()])
        self.assertEqual(result["state"], "success")
        self.assertEqual(result["reason"], "reviews_complete")
        self.assertTrue(result["reviews_complete"])
        resolution = result["security_review"]["resolution"]
        self.assertEqual(resolution["source"], "github_reaction")
        self.assertEqual(resolution["reacted_at"], REACTED)
        self.assertEqual(result["security_review"]["commit_sha"], SHA)
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

    def test_a_plus_one_older_than_the_last_completion_row_is_stale(self):
        for created in (
            "2026-11-03T00:23:44Z",
            "2026-11-03T00:23:15Z",
            "2026-11-02T23:59:59Z",
        ):
            result = self.evaluate([reaction(created=created)])
            self.assertEqual(result["state"], "pending", created)
        # Same second as the row: reactions carry seconds, the row microseconds.
        same_second = self.evaluate([reaction(created="2026-11-03T00:23:45Z")])
        self.assertEqual(same_second["state"], "success")

    def test_a_malformed_completion_row_blocks(self):
        for stamp in ("2026-11-03 00:23:45", "2026-02-30T00:00:00Z"):
            rows = (
                row_text("📝 **Code Review**", CODE_DONE),
                row_text("🔒 **Security Review**", stamp),
            )
            result = self.evaluate([reaction()], row=summary(rows=rows))
            self.assertEqual(result["state"], "blocked", stamp)
            self.assertEqual(result["reason"], "protocol")

    def test_finding_text_in_the_summary_voids_the_clean_path(self):
        for text in (
            "\n### Security findings\n\n#### Advisory findings (1)\n",
            "\n<!-- codex-security-review-finding:v1 -->\n",
        ):
            row = summary()
            row["body"] = row["body"].replace("\n<details>", text + "\n<details>", 1)
            m = module()
            with patch.object(
                m.runtime, "_api", side_effect=AssertionError("unexpected API")
            ):
                result = m.review_evidence([row], SHA, REPO, PR)
            self.assertEqual(result["state"], "pending", text)

    def test_rows_must_name_the_reviewed_head(self):
        rows = (
            row_text("📝 **Code Review**", CODE_DONE),
            row_text("🔒 **Security Review**", SECURITY_DONE, short=OTHER[:7]),
        )
        m = module()
        with patch.object(m.runtime, "_api", side_effect=AssertionError("unexpected")):
            result = m.review_evidence([summary(rows=rows)], SHA, REPO, PR)
        self.assertEqual(result["state"], "pending")

    def test_native_finding_threads_decide_after_the_reaction(self):
        resolved = page()["data"]["repository"]["pullRequest"]["reviewThreads"]["nodes"]
        self.assertEqual(
            self.evaluate([reaction()], thread_pages=threads(resolved))["state"],
            "success",
        )
        open_thread = [dict(resolved[0], isResolved=False, resolvedBy=None)]
        pending = self.evaluate([reaction()], thread_pages=threads(open_thread))
        self.assertEqual(pending["state"], "pending")
        self.assertFalse(pending["reviews_complete"])
        moved = threads()
        moved[0]["data"]["repository"]["pullRequest"]["headRefOid"] = OTHER
        blocked = self.evaluate([reaction()], thread_pages=moved)
        self.assertEqual(blocked["state"], "blocked")
        self.assertEqual(blocked["reason"], "head_moved")

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

    def test_only_table_rows_count_as_completion_rows(self):
        quoted_only = (
            row_text("📝 **Code Review**", CODE_DONE),
            "> " + row_text("🔒 **Security Review**", SECURITY_DONE),
        )
        m = module()
        with patch.object(m.runtime, "_api", side_effect=AssertionError("unexpected")):
            result = m.review_evidence([summary(rows=quoted_only)], SHA, REPO, PR)
        self.assertEqual(result["state"], "pending")
        with_copy = (
            row_text("📝 **Code Review**", CODE_DONE),
            row_text("🔒 **Security Review**", SECURITY_DONE),
            "> " + row_text("🔒 **Security Review**", "2026-11-02T00:00:00.000000Z"),
        )
        accepted = self.evaluate([reaction()], row=summary(rows=with_copy))
        self.assertEqual(accepted["state"], "success")

    def test_both_completion_rows_are_required_in_the_summary(self):
        only_security = (row_text("🔒 **Security Review**", SECURITY_DONE),)
        running = (
            row_text("📝 **Code Review**", CODE_DONE),
            "| 🔒 **Security Review** | 🔄 **Running** since x | `e8ab290` | x |",
        )
        twice = (
            row_text("🔒 **Security Review**", SECURITY_DONE),
            row_text("🔒 **Security Review**", SECURITY_DONE),
        )
        for rows in ((), only_security, running, twice):
            m = module()
            with patch.object(
                m.runtime, "_api", side_effect=AssertionError("unexpected API")
            ):
                result = m.review_evidence([summary(rows=rows)], SHA, REPO, PR)
            self.assertEqual(result["state"], "pending", rows)

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

    def test_malformed_reaction_records_block_without_a_verdict(self):
        for payload in ({}, [{}], [[{}]], [[{"content": "+1", "created_at": REACTED}]]):
            result = self.evaluate(payload, raw=True)
            self.assertEqual(result["state"], "blocked", payload)
            self.assertEqual(result["reason"], "protocol")
        for reactions in (
            [{"user": dict(CODEX), "created_at": REACTED}],
            [{"user": dict(CODEX), "content": "+1"}],
            [{"user": None, "content": "+1", "created_at": REACTED}],
            [{"user": dict(CODEX), "content": 1, "created_at": REACTED}],
            [reaction(created=None)],
            [reaction(created=1)],
            [reaction(created="2026-11-03 00:23:49")],
            [reaction(created="2026-11-03T00:23:49+00:00")],
            [reaction(created="2026-13-45T25:99:99Z")],
            [reaction("eyes", created=None), reaction()],
            ["+1"],
        ):
            result = self.evaluate(reactions)
            self.assertEqual(result["state"], "blocked", reactions)
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
