"""The review command file asks for no permission to load (ADR-1139, issue 1021).

In tag mode the review prompt does not reach the CLI as a slash command: the
model loads `/review-pr` with the Skill tool. A command file whose frontmatter
carries `allowed-tools` needs an approval for that call.
Source: probe of 2026-11-13, Claude Code 2.1.323, one run per arm, a command
file that differs by that one header: with it, `permission_denials` holds
`Skill`; without it, the command loads.
Not measured: the review job itself. In 3 reviews of 11 the review ran without
the command; that the approval was refused there is the reading that fits
their logs (ADR-1139, Measurement), not an observation.
"""

import shlex
import unittest
from pathlib import Path

import yaml

from tests_py.scripts._ci_native_claude_support import ACTION, find_step

ROOT = Path(__file__).resolve().parents[2]
COMMAND = ROOT / ".claude/commands/review-pr.md"
REVIEW = ROOT / ".github/workflows/claude-review.yml"
# The three commands the header allowed, which the review still needs.
GH_COMMANDS = ("Bash(gh pr comment:*)", "Bash(gh pr diff:*)", "Bash(gh pr view:*)")


def _frontmatter():
    text = COMMAND.read_text()
    assert text.startswith("---\n"), "the command file has no frontmatter"
    return yaml.safe_load(text.split("---\n", 2)[1])


class ReviewCommandLoads(unittest.TestCase):
    def test_the_command_file_carries_no_allowed_tools_header(self):
        self.assertNotIn("allowed-tools", _frontmatter())

    def test_the_command_file_still_describes_itself(self):
        # Only the description is held: another key (`argument-hint`, ...)
        # does not make the command need an approval.
        self.assertEqual(_frontmatter().get("description"), "Review a pull request")

    def test_the_workflow_allows_what_the_header_allowed(self):
        job = yaml.safe_load(REVIEW.read_text())["jobs"]["review"]
        args = shlex.split(find_step(job, uses=ACTION)["with"]["claude_args"])
        allowed = args[args.index("--allowedTools") + 1].split(",")
        for command in GH_COMMANDS:
            self.assertIn(command, allowed)


if __name__ == "__main__":
    unittest.main()
