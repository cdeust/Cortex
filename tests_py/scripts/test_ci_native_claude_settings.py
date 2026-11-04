"""The checked-in .claude/settings.json against the owner @claude mention job."""

import json
import re
import shlex
import subprocess
import unittest

from tests_py.scripts._ci_native_claude_support import (
    ACTION,
    ROOT,
    find_step,
    mention_job,
)

SETTINGS = ROOT / ".claude/settings.json"
# .claude/settings.json allow rules the job keeps beyond --allowedTools: ruff
# format rewrites files, which tag mode's Edit/Write already grant; python3 is
# a second name for the interpreter the job installed (#856 review).
SETTINGS_EXEMPT = {"ruff format", "python3 -m mcp_server.doctor"}
_BASH_RULE = re.compile(r"^Bash\(([^()*:;|&$`]+)( \*|:\*)?\)$")
# Deny rules of .claude/settings.json the mention job relies on: tag mode allows
# Read with no path limit and --disallowedTools mirrors only curl.
SETTINGS_DENY = {
    "Bash(curl:*)",
    "Read(.env)",
    "Read(.env.*)",
    "Read(**/.env)",
    "Read(**/.env.*)",
    "Read(**/.ssh/**)",
    "Read(~/.ssh/**)",
}


def _bash_rules(rules):
    """`(prefix, wildcard)` of `Bash(cmd)`, `Bash(cmd:*)` or `Bash(cmd *)` rules.

    `cmd:*` and `cmd *` are the equivalent word-bounded wildcards of Claude Code
    (`Bash(uv:*)` covers `uv x`, not `uvx`); `Bash(cmd)` is exact. A raw
    `Bash(cmd*)` is a string prefix, so it is rejected, as are a bare `Bash`, a
    non-Bash tool, a `*` elsewhere, shell operators, and stray or missing words.
    """
    parsed = []
    for rule in rules:
        match = _BASH_RULE.match(rule)
        if match is None or match.group(1) != " ".join(match.group(1).split()):
            raise AssertionError(f"not an exact or word-bounded Bash rule: {rule!r}")
        parsed.append((match.group(1), match.group(2) is not None))
    return parsed


def _covers(cli, rule):
    """A wildcard CLI entry covers the rule's prefix at a word boundary; an exact
    CLI entry covers only the identical exact rule."""
    (prefix, wildcard), (cmd, cmd_wildcard) = cli, rule
    if not wildcard:
        return not cmd_wildcard and cmd == prefix
    return cmd == prefix or cmd.startswith(prefix + " ")


class SettingsAgainstMentionJob(unittest.TestCase):
    def test_settings_allow_rules_map_to_allowed_denied_or_exempt(self):
        # The pinned action loads project settings and, on a PR, restores them
        # from the base branch (restore-config.ts), so main's .claude/settings.json
        # applies and the effective allowlist is the union. Every allow rule of
        # that file is a word-bounded Bash rule and falls under a prefix allowed
        # here, a prefix denied here (deny wins over allow) or a named exemption
        # the file still carries; the deny rules the job relies on stay in place.
        args = shlex.split(find_step(mention_job(), uses=ACTION)["with"]["claude_args"])
        # Readable on their own; CLAUDE_ARGS in test_ci_native_claude_mentions
        # pins the same facts exactly.
        self.assertNotIn("--setting-sources", args)
        self.assertEqual(args.count("--disallowedTools"), 1)
        allowed = _bash_rules(args[args.index("--allowedTools") + 1].split(","))
        denied = _bash_rules(args[args.index("--disallowedTools") + 1].split(","))
        self.assertIn(("uv", True), denied)
        self.assertIn(("curl", True), denied)
        # The action also loads settings.local.json and restores .claude/ from
        # the base branch, so a tracked copy (force-added past .gitignore) would
        # reach the job unchecked; the untracked local copy is fine.
        tracked = subprocess.run(
            ["git", "ls-files", "--", ".claude/settings.local.json"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        ).stdout
        self.assertEqual(tracked, "")
        settings = json.loads(SETTINGS.read_text())
        self.assertLessEqual(set(settings), {"$schema", "permissions"})
        self.assertLessEqual(set(settings["permissions"]), {"allow", "deny"})
        self.assertLessEqual(SETTINGS_DENY, set(settings["permissions"]["deny"]))
        rules = _bash_rules(settings["permissions"]["allow"])
        self.assertLessEqual(SETTINGS_EXEMPT, {cmd for cmd, _ in rules})
        for rule in rules:
            covered = any(_covers(cli, rule) for cli in allowed + denied)
            self.assertTrue(covered or rule[0] in SETTINGS_EXEMPT, rule)


if __name__ == "__main__":
    unittest.main()
