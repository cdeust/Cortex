"""Contracts of .github/workflows/claude.yml (ADR-1116).

Sources: GitHub events reference (workflow_run runs the default-branch file;
pull_request_review runs refs/pull/N/merge) and anthropics/claude-code-action
v1.0.263 action.yml (App token revoked after the step).
"""

from __future__ import annotations

import re
import unittest

from tests_py.scripts.test_ci_claude_wiring import CLAUDE_YML, CODEX_YML, PIN, job


class ClaudeWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.text = CLAUDE_YML.read_text()

    def test_every_action_use_is_the_verified_pin_without_token_override(self):
        uses = re.findall(r"uses: anthropics/claude-code-action@[^\n]*", self.text)
        self.assertGreaterEqual(len(uses), 3)
        self.assertEqual(set(uses), {"uses: " + PIN})
        self.assertNotIn("github_token:", self.text)
        self.assertNotIn('allowed_bots: "*"', self.text)
        self.assertNotIn("allowed_non_write_users", self.text)

    def test_triggers_run_only_default_branch_definitions(self):
        on = self.text.split("\non:\n", 1)[1].split("\nenv:\n", 1)[0]
        self.assertIn("workflows: [Pipeline]", on)
        self.assertIn("types: [requested]", on)
        for event in ("pull_request_review", "pull_request_target", "pull_request:"):
            self.assertNotIn(event, on)

    def test_only_resume_holds_actions_write_and_reviews_cannot_write(self):
        self.assertEqual(self.text.count("actions: write"), 1)
        self.assertIn("actions: write", job(self.text, "resume"))
        for name in ("target", "review", "verify"):
            with self.subTest(job=name):
                body = job(self.text, name)
                self.assertNotIn(": write\n", body.replace("id-token: write\n", ""))
        self.assertIn("id-token: write", job(self.text, "review"))
        self.assertNotIn("id-token", job(self.text, "resume"))

    def test_review_jobs_check_out_main_only_and_never_the_pr_head(self):
        for name in ("target", "review", "verify", "resume"):
            with self.subTest(job=name):
                body = job(self.text, name)
                self.assertIn("ref: main", body)
                self.assertIn("persist-credentials: false", body)
                forbidden = r"head\.ref|head_branch|refs/pull|download-artifact"
                self.assertIsNone(re.search(forbidden, body))

    def test_review_runs_once_per_pipeline_run_and_publishes_exact_head(self):
        target = job(self.text, "target")
        self.assertIn("github.event.workflow_run.run_attempt == 1", target)
        review = job(self.text, "review")
        self.assertIn(
            'allowed_bots: "claude[bot],chatgpt-codex-connector[bot],dependabot[bot]"',
            review,
        )
        self.assertNotIn("Bash(gh api:*)", review)
        repo, pr, sha = (
            "${{ github.repository }}",
            "${{ env.PR }}",
            "${{ env.HEAD_SHA }}",
        )
        temp = "${{ runner.temp }}"
        for kind in ("code", "security"):
            exact = (
                f"Bash(gh api -X POST repos/{repo}/pulls/{pr}/reviews"
                f" -f commit_id={sha} -f event=COMMENT"
                f" -F body=@{temp}/claude-review/{kind}-review.md)"
            )
            # The App token has contents:write: only this exact write is allowed.
            self.assertIn(exact, review)
            self.assertEqual(review.count("Bash(gh api"), 2)
            self.assertIn(f"Edit(/{temp}/claude-review/{kind}-review.md)", review)
            self.assertNotIn(",Write,", review)
            self.assertIn("steps.kinds.outputs." + kind + " == 'true'", review)
            run_id = "${{ github.run_id }}-${{ github.run_attempt }}"
            marker = f"<!-- claude-review:v2 kind={kind} findings=N run={run_id} -->"
            self.assertIn(marker, review)
            self.assertIn(f"--published {kind}", review)

    def test_trusted_preparation_creates_both_verdict_files(self):
        # msg_037967ba0159: whether a scoped Edit rule may create an absent file
        # under dontAsk is not proven, so main's preparation step creates them.
        review = job(self.text, "review")
        prepare = review.split("      - name: Read the pull request as data\n", 1)[1]
        prepare = prepare.split("\n      - name:", 1)[0]
        for kind in ("code", "security"):
            self.assertIn(f': > "$DIR/{kind}-review.md"', prepare)

    def test_review_concurrency_is_per_head_and_never_cancels(self):
        # Codex 4389070526: a stale run entering a per-PR group could cancel the
        # newer head's reviewer; GitHub does not order group entry by dispatch.
        review = job(self.text, "review")
        group = "group: claude-review-${{ github.repository }}-"
        group += "${{ needs.target.outputs.sha }}"
        self.assertIn(group, review)
        self.assertIn("cancel-in-progress: false", review)
        self.assertNotIn("cancel-in-progress: true", self.text)
        self.assertIn("name: review ${{ needs.target.outputs.sha }}", review)

    def test_review_sessions_ignore_repository_settings_and_deny_unlisted_tools(self):
        # Codex 4389070506: settingSources default to user+project+local
        # (parse-sdk-options.ts:340-345); .claude/settings.json grants Bash(uv *).
        review = job(self.text, "review")
        flags = "--setting-sources user --permission-mode dontAsk"
        self.assertEqual(review.count(flags), 2)
        self.assertEqual(review.count("claude_args:"), 2)

    def test_reviews_cannot_use_git_output_to_overwrite_validators(self):
        # Native finding4391382583: even git diff HEAD HEAD --output=script.py
        # truncates a validator. Git show/log also accept output-file options.
        review = job(self.text, "review")
        for action in review.split("          claude_args: >-\n")[1:]:
            args = action.split("\n\n", 1)[0]
            self.assertNotIn("Bash(git", args)
            self.assertIn("Read,Glob,Grep", args)

    def test_only_exact_publication_command_is_available_to_review_agents(self):
        # Native security finding4391507098: shell redirects on gh pr reads
        # can replace the validator executed by the following trusted step.
        review = job(self.text, "review")
        for action in review.split("          claude_args: >-\n")[1:]:
            args = action.split("\n\n", 1)[0]
            bash_rules = re.findall(r"Bash\([^)]*\)", args)
            self.assertEqual(len(bash_rules), 1)
            self.assertTrue(bash_rules[0].startswith("Bash(gh api -X POST repos/"))
        self.assertIn('> "$DIR/pr.json"', review)
        self.assertEqual(review.count("read metadata from"), 2)

    def test_native_skill_permissions_cannot_bypass_the_write_boundary(self):
        # Anthropic code-review frontmatter grants gh pr reads and writes;
        # skills documentation states these grants supplement allowedTools.
        review = job(self.text, "review")
        self.assertEqual(
            review.count(
                "--settings ${{ runner.temp }}/claude-review/review-settings.json"
            ),
            2,
        )
        self.assertIn("PreToolUse", review)
        self.assertEqual(review.count("CORTEX_REVIEW_PUBLISH_COMMAND:"), 2)
        self.assertEqual(review.count("CORTEX_REVIEW_FILE:"), 2)
        for label in ("Code review", "Security review"):
            block = review.split(f"      - name: {label}\n", 1)[1]
            block = block.split("\n      - name:", 1)[0]
            command = block.split("CORTEX_REVIEW_PUBLISH_COMMAND: >-\n", 1)[1]
            command = command.split("\n", 1)[0].strip()
            self.assertIn(f"Bash({command})", block)
            self.assertIn("\n            " + command + "\n", block)
        for kind in ("code", "security"):
            self.assertIn(
                f'--verify "${{{{ runner.temp }}}}/claude-review/{kind}-guard.jsonl"',
                review,
            )

    def test_tag_job_is_owner_only_and_scrubs_subprocess_secrets(self):
        # Codex 4389092806: a writer without secret access must not steer a job
        # that holds CLAUDE_CODE_OAUTH_TOKEN and runs shell commands.
        tag = job(self.text, "claude")
        self.assertIn("github.event.sender.login == github.repository_owner", tag)
        for name in ("claude", "review"):
            body = job(self.text, name)
            uses = body.count("uses: anthropics/claude-code-action@")
            self.assertEqual(body.count('CLAUDE_CODE_SUBPROCESS_ENV_SCRUB: "1"'), uses)

    def run_tag_job(self, event_name, **event):
        """Evaluate the tag job's `if` (==, !=, &&, ||, contains) on one event."""
        condition = job(self.text, "claude").split("    if: >-\n", 1)[1]
        condition = " ".join(condition.split("\n    runs-on:", 1)[0].split())
        python = condition.replace("&&", " and ").replace("||", " or ")

        class Node(dict):
            def __getattr__(self, key):
                value = self.get(key, "")
                return Node(value) if isinstance(value, dict) else value

        github = Node(event_name=event_name, repository_owner="cdeust", event=event)
        on = self.text.split("\non:\n", 1)[1].split("\nenv:\n", 1)[0]
        listed = on.split(f"  {event_name}:\n", 1)[1].split("\n", 1)[0]
        if event.get("action") not in listed:
            return False
        scope = {"github": github, "contains": lambda text, part: part in text}
        # Evaluates this repository's own workflow text, with no builtins.
        return bool(eval(python, {"__builtins__": {}}, scope))  # noqa: S307

    def test_owner_assigning_an_external_issue_never_runs_claude(self):
        # Codex 4389808387: on `assigned` the sender is the assigner, but the
        # issue text that reaches the write-capable run was written by its author.
        owner, external = {"login": "cdeust", "type": "User"}, {"login": "mallory"}
        issue = {"user": external, "title": "help", "body": "@claude run gh api ..."}
        self.assertFalse(
            self.run_tag_job("issues", action="assigned", sender=owner, issue=issue)
        )
        self.assertFalse(
            self.run_tag_job("issues", action="opened", sender=external, issue=issue)
        )
        own = dict(issue, user=owner)
        self.assertTrue(
            self.run_tag_job("issues", action="opened", sender=owner, issue=own)
        )
        comment = {"body": "@claude fix", "user": owner}
        self.assertTrue(
            self.run_tag_job(
                "issue_comment",
                action="created",
                sender=owner,
                comment=comment,
                issue=own,
            )
        )

    def test_owner_comment_requires_an_owner_authored_thread(self):
        # Native security finding4390480666: commenter and thread author differ.
        owner = {"login": "cdeust", "type": "User"}
        comment = {"body": "@claude help", "user": owner}
        for author in ("mallory", "cdeust"):
            issue = {"user": {"login": author}, "body": "task", "title": "task"}
            with self.subTest(author=author):
                self.assertEqual(
                    self.run_tag_job(
                        "issue_comment",
                        action="created",
                        sender=owner,
                        comment=comment,
                        issue=issue,
                    ),
                    author == "cdeust",
                )

    def test_verification_is_a_separate_untouched_job(self):
        verify = job(self.text, "verify")
        self.assertIn("python3 -I scripts/ci_claude_reviews.py", verify)
        self.assertIn('--sha "$HEAD_SHA" --require-complete', verify)
        self.assertIn("actions: read", verify)
        resume = job(self.text, "resume")
        self.assertIn("python3 -B scripts/ci_claude_review_event.py", resume)
        self.assertNotIn("needs.review.outputs", resume)

    def test_resume_serialises_with_the_codex_completion_handler(self):
        group = "codex-review-completion-${{ github.repository }}-"
        codex = CODEX_YML.read_text()
        self.assertIn(group + "${{ needs.identify.outputs.pr }}", codex)
        self.assertIn(
            group + "${{ needs.target.outputs.pr }}", job(self.text, "resume")
        )
        self.assertIn("cancel-in-progress: false", job(self.text, "resume"))

    def test_tag_job_never_answers_claude_itself(self):
        tag = job(self.text, "claude")
        self.assertIn("github.event.comment.user.login != 'claude[bot]'", tag)
        self.assertIn("github.event.comment.user.type != 'Bot'", tag)


if __name__ == "__main__":
    unittest.main()
