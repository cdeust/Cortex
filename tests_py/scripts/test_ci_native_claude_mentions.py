"""Regression guards for the owner @claude mention workflow (claude.yml)."""

import re
import shlex
import tomllib
import unittest

from tests_py.scripts._ci_native_claude_support import (
    ACTION,
    GUARD,
    ROOT,
    find_step,
    mention_job,
)

CLAUDE_ARGS = [
    "--strict-mcp-config",
    "--allowedTools",
    "Bash(pytest:*),Bash(ruff check:*),Bash(ruff format --check:*),"
    "Bash(python -m mcp_server.doctor:*),"
    "Bash(python scripts/check_craftsmanship.py:*),"
    "Bash(git status:*),Bash(git diff:*),Bash(git log:*),"
    "Bash(gh run view:*)",
    "--disallowedTools",
    "Bash(uv:*),Bash(curl:*)",
    "--model",
    "claude-opus-5-5",
]


def _canonical(requirement):
    """PEP 503 name of a requirement string, without specifier, marker or URL."""
    name = re.split(r"[<>=!~;@\[ ]", requirement.strip(), maxsplit=1)[0]
    return re.sub(r"[-_.]+", "-", name).lower()


class OwnerMentionTests(unittest.TestCase):
    def test_owner_mentions_keep_app_authentication(self):
        mention = mention_job()
        self.assertEqual(mention["permissions"]["id-token"], "write")
        invocation = find_step(mention, uses=ACTION)
        self.assertNotIn("github_token", invocation["with"])
        checkout = find_step(mention, uses="actions/checkout@")
        self.assertFalse(checkout["with"]["persist-credentials"])

    def test_owner_mentions_inherit_tag_mode_accept_edits(self):
        # Upstream src/modes/tag/index.ts:158-214 grants workspace edits only
        # through --permission-mode acceptEdits; base-action parse-sdk-options.ts
        # keeps the last --permission-mode, so any workflow value replaces it.
        # Runs 40645284158 and 40645479186 were refused every Edit and Write.
        mention = mention_job()
        invocation = find_step(mention, uses=ACTION)
        self.assertEqual(invocation["uses"], ACTION)
        self.assertEqual(
            set(invocation["with"]),
            {"claude_code_oauth_token", "include_comments_by_actor", "claude_args"},
        )
        self.assertEqual(
            invocation["with"]["include_comments_by_actor"],
            "${{ github.repository_owner }}",
        )
        self.assertNotIn("--permission-mode", invocation["with"]["claude_args"])
        self.assertEqual(mention["permissions"]["contents"], "write")

    def test_owner_mentions_gate_on_the_owner_and_their_threads(self):
        # Pin both branches and the outer sender gate, including their grouping.
        expected = (
            "github.event.sender.login == github.repository_owner "
            "&& ((github.event_name == 'issue_comment' "
            "&& contains(github.event.comment.body, '@claude') "
            "&& github.event.issue.user.login == github.repository_owner "
            "&& github.event.comment.user.login != 'claude[bot]' "
            "&& github.event.comment.user.type != 'Bot') "
            "|| (github.event_name == 'issues' "
            "&& github.event.issue.user.login == github.repository_owner "
            "&& (contains(github.event.issue.body, '@claude') "
            "|| contains(github.event.issue.title, '@claude'))))"
        )
        self.assertEqual(" ".join(mention_job()["if"].split()), expected)

    def test_owner_mentions_allow_the_validation_commands_only(self):
        # Tag mode supplies no shell allowlist beyond its own scoped git
        # (src/modes/tag/index.ts:158-214 at the pinned SHA); headless, anything
        # that falls through to "ask" is denied, and .claude/settings.json adds
        # its rules (test_ci_native_claude_settings).
        # The list is CLAUDE.md's validation set, git inspection and gh run view:
        # no uv sync (the job installs the
        # environment; test_uv_lock_single_source.py), no bare interpreter, no
        # gh api, no gh pr comment (tag mode owns its tracking comment).
        invocation = find_step(mention_job(), uses=ACTION)
        args = shlex.split(invocation["with"]["claude_args"])
        self.assertEqual(args, CLAUDE_ARGS)
        self.assertEqual(
            invocation["env"],
            {
                "CLAUDE_CODE_SUBPROCESS_ENV_SCRUB": "1",
                "CORTEX_MEMORY_STORE_BACKEND": "sqlite",
                "CORTEX_RERANKER_OFFLINE": "1",
                "HF_HUB_OFFLINE": "1",
                "TRANSFORMERS_OFFLINE": "1",
            },
        )

    def test_owner_mentions_install_the_tested_environment_before_the_agent(self):
        # Python 3.12 and ci.json "regression"'s dev+sqlite+codebase extras on the
        # SQLite backend; ruff lives in the lint group; the embedding contract
        # test needs the model; the build backend comes from the packaging group.
        job = mention_job()
        steps = job["steps"]
        python = find_step(job, uses="actions/setup-python@")
        locked = find_step(job, uses="./.github/actions/uv-locked-install")
        project = find_step(job, name="Install the project")
        model = find_step(job, name="Pre-download embedding model")
        action = find_step(job, uses=ACTION)
        order = [steps.index(s) for s in (python, locked, project, model, action)]
        self.assertEqual(order, sorted(order))
        self.assertEqual(python["with"], {"python-version": "3.12"})
        self.assertEqual(
            locked["with"],
            {
                "set": "--extra dev --extra sqlite --extra codebase "
                "--group lint --group packaging",
                "environment": "${{ env.pythonLocation }}",
            },
        )
        # Not editable: hatchling's editable hook needs `editables`, absent
        # from uv.lock (Codex P1 on #856); the wheel build does not.
        self.assertEqual(project["run"], "pip install --no-deps --no-build-isolation .")
        self.assertEqual(project["env"], {"PIP_DISABLE_PIP_VERSION_CHECK": "1"})
        self.assertIn("SentenceTransformer('all-MiniLM-L6-v2'", model["run"])
        # 5 attempts of at most 60 s and sleeps of 10+20+30+40 s fit the step.
        self.assertIn("timeout 60 python -c", model["run"])
        self.assertIn("for attempt in 1 2 3 4 5;", model["run"])
        run = model["run"]
        self.assertLess(
            run.index('[ "$attempt" -lt 5 ] || break'), run.index("sleep $((")
        )
        self.assertIn("sleep $((attempt * 10))", run)
        worst = 5 * 60 + sum(10 * a for a in range(1, 5))
        self.assertLess(worst, model["timeout-minutes"] * 60)

    def test_non_isolated_install_is_never_editable(self):
        # Invariant behind the literal above: build-system.requires lists what
        # a wheel build needs; an editable build adds hatchling's `editables`,
        # which no selected group carries (Codex P1, Claude review on #856).
        run = shlex.split(find_step(mention_job(), name="Install the project")["run"])
        self.assertIn("--no-build-isolation", run)
        editable = [a for a in run if a.startswith(("-e", "--editable"))]
        self.assertEqual(editable, [], run)

    def test_non_isolated_build_takes_its_backend_from_a_selected_locked_group(self):
        # Invariant, not literal (Codex P1 on #856): with --no-build-isolation,
        # every build-system requirement must come from a dependency group the
        # set selects with --group/--only-group (an --extra is not a group).
        job = mention_job()
        project = find_step(job, name="Install the project")
        self.assertIn("--no-build-isolation", project["run"])
        tokens = shlex.split(
            find_step(job, uses="./.github/actions/uv-locked-install")["with"]["set"]
        )
        groups = {
            v
            for f, v in zip(tokens, tokens[1:], strict=False)
            if f in ("--group", "--only-group")
        }
        pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
        requires = pyproject["build-system"]["requires"]
        self.assertTrue(requires)
        for requirement in requires:
            name = _canonical(requirement)
            providers = {
                group
                for group, deps in pyproject["dependency-groups"].items()
                if any(_canonical(dep) == name for dep in deps if isinstance(dep, str))
            }
            self.assertTrue(
                providers & groups, f"{name}: in {providers}, selected {groups}"
            )

    def test_owner_mentions_authorize_the_fix_target_before_checkout(self):
        # The sender gate checks who asked, not which head the pinned action
        # checks out and pushes to (src/modes/tag/index.ts). The guard is the
        # first step, before any checkout, and carries no escape hatch.
        job = mention_job()
        steps = job["steps"]
        guard = find_step(job, name=GUARD)
        checkout = find_step(job, uses="actions/checkout@")
        self.assertIs(steps[0], guard)
        self.assertIs(steps[1], checkout)
        self.assertEqual(
            guard["env"],
            {
                "GH_TOKEN": "${{ github.token }}",
                "GH_REPO": "${{ github.repository }}",
                "ISSUE_NUMBER": "${{ github.event.issue.number }}",
            },
        )
        self.assertEqual(set(guard) - {"name", "env", "run", "timeout-minutes"}, set())

    def test_owner_mentions_bound_the_run(self):
        # source: docs.github.com workflow-syntax#jobsjob_idtimeout-minutes;
        # the default is 360 minutes and the queue serializes per thread. Every
        # step before the agent carries its own bound (guard, checkout, apt,
        # python, locked install, project, model: 28 minutes in the worst
        # case), leaving the agent at least 30 of the job's 60 minutes.
        job = mention_job()
        self.assertEqual(job["timeout-minutes"], 60)
        steps = job["steps"]
        before_agent = steps[: steps.index(find_step(job, uses=ACTION))]
        bounds = [step.get("timeout-minutes") for step in before_agent]
        self.assertEqual(bounds, [2, 3, 3, 2, 8, 3, 7])
        self.assertTrue(all(type(b) is int for b in bounds), bounds)
        self.assertGreaterEqual(job["timeout-minutes"] - sum(bounds), 30)

    def test_owner_mentions_serialize_branch_writes(self):
        # source: https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency
        self.assertEqual(
            mention_job()["concurrency"],
            {
                "group": "claude-mentions-${{ github.event.issue.number }}",
                "cancel-in-progress": False,
                "queue": "max",
            },
        )


if __name__ == "__main__":
    unittest.main()
