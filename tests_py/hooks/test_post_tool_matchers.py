"""Light routing and aggregation tests; timings below are synthetic fixtures.

source: Claude Code hooks reference, matcher-patterns and hook-handler-fields;
the hook guards themselves define each accepted tool set.
Run: python -S -m unittest tests_py.hooks.test_post_tool_matchers
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from mcp_server.hooks import (
    pipeline_impact_bump,
    post_commit_reindex,
    preemptive_context,
)
from scripts import aggregate_hook_timings as timing

_PLUGIN = Path(__file__).resolve().parents[2] / ".claude-plugin" / "plugin.json"
_PREFIX = "mcp_server.hooks."
_CAPTURE = _PREFIX + "post_tool_capture"


def synthetic_report(plugin_path: Path) -> dict:
    """Made-up values test arithmetic only; never benchmark evidence."""
    raw = plugin_path.read_bytes()
    plugin = json.loads(raw)
    cases = []
    for tool in ("Read", "Bash"):
        samples = [
            {
                "repetition": rep,
                "module": module,
                "exit_code": 0,
                "user_seconds": 1,
                "system_seconds": 2,
                "wall_seconds": 4,
                "max_rss_native": 5,
            }
            for rep in range(timing.REPETITIONS)
            for module in timing.selected_modules(plugin, tool)
        ]
        cases.append({"payload": {"tool_name": tool}, "samples": samples})
    return {
        "entrypoint": "module",
        "python": "test-python",
        "platform": "test-os",
        "plugin_sha256": hashlib.sha256(raw).hexdigest(),
        "cases": cases,
    }


class MatcherTests(unittest.TestCase):
    def setUp(self):
        self.plugin = json.loads(_PLUGIN.read_text())

    def test_file_matchers_follow_real_guard_sets(self):
        accepted = {
            "preemptive_context": preemptive_context._FILE_TOOLS,
            "pipeline_impact_bump": pipeline_impact_bump._FILE_TOOLS,
        }
        for module, tools in accepted.items():
            routed = {
                tool
                for tool in ("Read", "Edit", "Write", "MultiEdit", "Bash")
                if _PREFIX + module in timing.selected_modules(self.plugin, tool)
            }
            self.assertEqual(routed, tools)

    def test_bash_reindex_matcher_follows_real_guard(self):
        with patch.object(
            post_commit_reindex, "_is_commit_command", return_value=False
        ) as check:
            post_commit_reindex.process_event({"tool_name": "Read"})
            check.assert_not_called()
            post_commit_reindex.process_event({"tool_name": "Bash"})
            check.assert_called_once_with("")
        self.assertIn(
            _PREFIX + "post_commit_reindex",
            timing.selected_modules(self.plugin, "Bash"),
        )
        self.assertNotIn(
            _PREFIX + "post_commit_reindex",
            timing.selected_modules(self.plugin, "Read"),
        )

    def test_capture_keeps_every_tool_for_cascade_tick(self):
        groups = self.plugin["hooks"]["PostToolUse"]
        capture = [
            group for group in groups if _CAPTURE in group["hooks"][0]["command"]
        ]
        self.assertEqual(len(capture), 1)
        self.assertEqual(capture[0]["matcher"], "*")
        for tool in (
            "Grep",
            "Glob",
            "NotebookEdit",
            "WebFetch",
            "WebSearch",
            "mcp__x__y",
            "NewTool",
        ):
            self.assertEqual(timing.selected_modules(self.plugin, tool), {_CAPTURE})

    def test_matchers_do_not_match_partial_or_wrong_case_names(self):
        for tool in ("NotebookEdit", "ReadFile", "SomeWrite", "bash", "edit", ""):
            self.assertEqual(timing.selected_modules(self.plugin, tool), {_CAPTURE})

    def test_every_handler_is_preserved_exactly_once(self):
        modules = set()
        for tool in ("Edit", "Write", "Read", "MultiEdit", "Bash"):
            modules.update(timing.selected_modules(self.plugin, tool))
        self.assertEqual(modules, timing.MODULES)


class AggregationTests(unittest.TestCase):
    def setUp(self):
        self.plugin = json.loads(_PLUGIN.read_text())
        self.report = synthetic_report(_PLUGIN)
        self.case = self.report["cases"][0]

    def test_cpu_sum_first_discarded_and_individual_rss_retained(self):
        result = timing.aggregate_case(self.case, self.plugin)
        rows = result["repetitions"]
        self.assertEqual(
            [row["discarded"] for row in rows], [True, False, False, False]
        )
        self.assertEqual(rows[1]["cpu_seconds"], 6)
        self.assertEqual(rows[1]["wall_seconds_sum"], 8)
        self.assertEqual([hook["max_rss_native"] for hook in rows[1]["hooks"]], [5, 5])

    def test_raw_bsd_time_log_is_parsed_without_entering_metrics_manually(self):
        raw = (
            "hook stderr\n  4.00 real  1.00 user  2.00 sys\n"
            "  5 maximum resident set size\n"
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "time.log"
            path.write_text(raw)
            measured = timing._measured_sample({"time_log": str(path)})
        self.assertEqual(measured["user_seconds"] + measured["system_seconds"], 3)
        self.assertEqual(measured["wall_seconds"], 4)
        self.assertEqual(measured["max_rss_native"], 5)

    def test_missing_ambiguous_and_mixed_timing_data_are_rejected(self):
        row = " 4.00 real 1.00 user 2.00 sys\n 5 maximum resident set size\n"
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "time.log"
            for raw in ("", row + row):
                path.write_text(raw)
                with self.assertRaises(ValueError):
                    timing.read_time_log(path)
        with self.assertRaises(ValueError):
            timing._measured_sample({"time_log": "unused", "user_seconds": 1})

    def test_missing_duplicate_and_unexpected_samples_are_rejected(self):
        samples = self.case["samples"]
        altered = (
            samples[:-1],
            samples + [samples[0]],
            [{**samples[0], "module": "unknown"}, *samples[1:]],
        )
        for replacement in altered:
            with self.assertRaises(ValueError):
                timing.aggregate_case(
                    {**self.case, "samples": replacement}, self.plugin
                )

    def test_invalid_metrics_and_failed_runs_are_rejected(self):
        for bad in (float("nan"), float("inf"), -1, True, "0.1"):
            sample = {**self.case["samples"][0], "user_seconds": bad}
            with self.assertRaises(ValueError):
                timing._sample_key(sample)
        with self.assertRaises(ValueError):
            timing._sample_key({**self.case["samples"][0], "exit_code": 1})

    def test_entrypoint_and_payload_mismatches_are_rejected(self):
        for field, value in (
            ("entrypoint", "launcher"),
            ("python", "other"),
            ("platform", "other"),
        ):
            with self.assertRaises(ValueError):
                timing.compare_reports(
                    self.report, {**self.report, field: value}, (_PLUGIN, _PLUGIN)
                )
        after = copy.deepcopy(self.report)
        after["cases"][0]["payload"]["tool_input"] = {}
        with self.assertRaises(ValueError):
            timing.compare_reports(self.report, after, (_PLUGIN, _PLUGIN))

    def test_plugin_fingerprint_and_required_payloads_are_checked(self):
        with self.assertRaises(ValueError):
            timing.validate_report({**self.report, "plugin_sha256": "stale"}, _PLUGIN)
        with self.assertRaises(ValueError):
            timing.validate_report({**self.report, "cases": [self.case]}, _PLUGIN)

    def test_before_four_hooks_after_two_hooks_aggregate_actual_routes(self):
        before_plugin = copy.deepcopy(self.plugin)
        for group in before_plugin["hooks"]["PostToolUse"]:
            group["matcher"] = "*"
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "before.json"
            path.write_text(json.dumps(before_plugin))
            before = synthetic_report(path)
            result = timing.compare_reports(before, self.report, (path, _PLUGIN))
        for case in result["cases"]:
            self.assertEqual(len(case["retained_deltas"]), 3)
            self.assertTrue(
                all(
                    row["cpu_seconds_after_minus_before"] == -6
                    for row in case["retained_deltas"]
                )
            )


if __name__ == "__main__":
    unittest.main()
