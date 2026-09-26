"""Cleanup timing routes are complete, with legacy snapshot compatibility.

source: ADR-0703 ADR-1092
"""

import copy
import json
import unittest

from scripts import aggregate_hook_timings as timing
from tests_py.hooks.test_post_tool_matchers import _PLUGIN, synthetic_report


class CleanupTimingRoutesTests(unittest.TestCase):
    def setUp(self):
        self.plugin = json.loads(_PLUGIN.read_text())
        self.report = synthetic_report(_PLUGIN)
        self.case = self.report["cases"][0]

    def test_missing_cleanup_samples_cannot_underreport_timings(self):
        samples = [
            row for row in self.case["samples"] if row["module"] != timing.CLEANUP_ID
        ]
        with self.assertRaisesRegex(ValueError, "every routed hook"):
            timing.aggregate_case({**self.case, "samples": samples}, self.plugin)

    def test_legacy_snapshot_accepts_only_four_module_hooks(self):
        legacy = copy.deepcopy(self.plugin)
        legacy["hooks"]["PostToolUse"] = [
            group
            for group in legacy["hooks"]["PostToolUse"]
            if group["hooks"][0]["command"] != timing.CLEANUP_COMMAND
        ]
        samples = [
            row for row in self.case["samples"] if row["module"] != timing.CLEANUP_ID
        ]
        result = timing.aggregate_case({**self.case, "samples": samples}, legacy)
        self.assertNotIn(timing.CLEANUP_ID, result["modules"])
        self.assertEqual(result["repetitions"][1]["cpu_seconds"], 6)
        with self.assertRaisesRegex(ValueError, "every routed hook"):
            timing.aggregate_case(self.case, legacy)

    def test_unknown_and_malformed_cleanup_commands_are_rejected(self):
        for command in (
            "python3 unknown.py",
            timing.CLEANUP_COMMAND.replace("claude hook", "codex hook"),
            timing.CLEANUP_COMMAND.replace("PostToolUse", "Stop"),
            timing.CLEANUP_COMMAND + " extra",
            timing.CLEANUP_COMMAND + " mcp_server.hooks.post_tool_capture",
        ):
            plugin = copy.deepcopy(self.plugin)
            plugin["hooks"]["PostToolUse"][-1]["hooks"][0]["command"] = command
            with self.subTest(command=command), self.assertRaises(ValueError):
                timing.selected_modules(plugin, "Read")

    def test_duplicate_cleanup_and_missing_required_modules_are_rejected(self):
        duplicate = copy.deepcopy(self.plugin)
        groups = duplicate["hooks"]["PostToolUse"]
        groups.append(copy.deepcopy(groups[-1]))
        missing = copy.deepcopy(self.plugin)
        missing["hooks"]["PostToolUse"].pop(0)
        duplicate_module = copy.deepcopy(self.plugin)
        groups = duplicate_module["hooks"]["PostToolUse"]
        groups.append(copy.deepcopy(groups[0]))
        for plugin in (duplicate, missing, duplicate_module):
            with self.assertRaisesRegex(ValueError, "Missing, unexpected or duplicate"):
                timing.selected_modules(plugin, "Read")

    def test_non_command_cleanup_handler_is_rejected(self):
        self.plugin["hooks"]["PostToolUse"][-1]["hooks"][0]["type"] = "prompt"
        with self.assertRaisesRegex(ValueError, "command hook"):
            timing.selected_modules(self.plugin, "Read")
