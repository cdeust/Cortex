"""Exercise the review gate through raw SDK files and its real CLI."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "ci_review_execution.py"


def success():
    return {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "permission_denials": [],
    }


def agent_run(name="Agent"):
    return [
        {"type": "system", "subtype": "init"},
        {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "agent-1",
                        "name": name,
                        "input": {"prompt": "Review the diff"},
                    }
                ]
            },
        },
        {
            "type": "user",
            "tool_use_result": {"status": "completed"},
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "agent-1",
                        "content": "Review completed",
                    }
                ]
            },
        },
        success(),
    ]


class ReviewExecutionTests(unittest.TestCase):
    def run_gate(self, value, *, agents=False, raw=False):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "execution.json"
            path.write_text(value if raw else json.dumps(value), encoding="utf-8")
            return subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    str(path),
                    *(["--require-agents"] if agents else []),
                ],
                text=True,
                capture_output=True,
                check=False,
            )

    def rejected(self, value, category, *, agents=False):
        result = self.run_gate(value, agents=agents)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn(category, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_successful_synchronous_agents_and_legacy_tasks(self):
        for name in ("Agent", "Task"):
            with self.subTest(name=name):
                result = self.run_gate(agent_run(name), agents=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("execution verified", result.stdout)

    def test_fix_execution_does_not_require_agent(self):
        result = self.run_gate([success()])
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_nominal_success_cannot_hide_observed_permission_denial(self):
        messages = agent_run()
        messages[-1]["permission_denials"] = [
            {"tool_name": "Bash", "tool_input": {"command": "PRIVATE_TOKEN"}}
        ]
        result = self.run_gate(messages, agents=True)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("permission", result.stderr)
        self.assertNotIn("PRIVATE_TOKEN", result.stderr)

    def test_missing_or_malformed_permission_denials_are_rejected(self):
        for value in (None, False, 0, {}, "", "PRIVATE_TOKEN"):
            with self.subTest(value=value):
                result = success()
                result["permission_denials"] = value
                self.rejected([result], "permission")
        result = success()
        del result["permission_denials"]
        self.rejected([result], "permission")

    def test_result_must_be_single_and_terminal(self):
        for messages in (
            [],
            [{"type": "system", "subtype": "init"}],
            [success(), success()],
            [success(), {"type": "system", "subtype": "status"}],
        ):
            with self.subTest(messages=messages):
                self.rejected(messages, "result")

    def test_result_requires_success_and_literal_false_error_flag(self):
        for field, value in (
            ("subtype", "error_max_turns"),
            ("subtype", None),
            ("is_error", True),
            ("is_error", 0),
            ("is_error", None),
        ):
            with self.subTest(field=field, value=value):
                result = success()
                result[field] = value
                self.rejected([result], "result")
        result = success()
        del result["is_error"]
        self.rejected([result], "result")

    def test_invalid_container_messages_and_json_are_rejected(self):
        for messages in ({}, None, "PRIVATE_TOKEN", [None], ["PRIVATE_TOKEN"], [{}]):
            with self.subTest(messages=messages):
                self.rejected(messages, "message")

    def test_malformed_json_is_rejected(self):
        result = self.run_gate("{PRIVATE_TOKEN", raw=True)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("JSON", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_explicit_permission_denied_system_event_is_rejected(self):
        self.rejected(
            [{"type": "system", "subtype": "permission_denied"}, success()],
            "permission",
        )

    def test_tool_errors_and_malformed_error_flags_are_rejected(self):
        for flag in (True, 0, None, "false"):
            with self.subTest(flag=flag):
                messages = agent_run()
                messages[2]["message"]["content"][0]["is_error"] = flag
                self.rejected(messages, "tool")

    def test_review_requires_completed_agent_and_rejects_unmatched_results(self):
        self.rejected([success()], "agent", agents=True)
        messages = agent_run()
        del messages[2]
        self.rejected(messages, "tool", agents=True)
        messages = agent_run()
        messages[2]["message"]["content"][0]["tool_use_id"] = "unknown"
        self.rejected(messages, "tool", agents=True)
        messages = agent_run()
        messages[1], messages[2] = messages[2], messages[1]
        self.rejected(messages, "tool", agents=True)

    def test_background_agent_launch_is_not_completion(self):
        messages = agent_run()
        messages[1]["message"]["content"][0]["input"]["run_in_background"] = True
        self.rejected(messages, "agent", agents=True)

    def test_async_agent_acknowledgment_without_input_flag_is_not_completion(self):
        for name in ("Agent", "Task"):
            messages = agent_run(name)
            messages[2]["tool_use_result"] = {"status": "async_launched"}
            self.rejected(messages, "agent", agents=True)
            self.rejected(messages, "agent")

    def test_agent_result_cannot_share_structured_output_with_other_results(self):
        messages = agent_run()
        messages[1]["message"]["content"].append(
            {"type": "tool_use", "id": "agent-2", "name": "Agent", "input": {}}
        )
        messages[2]["message"]["content"].append(
            {"type": "tool_result", "tool_use_id": "agent-2", "content": "launched"}
        )
        self.rejected(messages, "shares a message", agents=True)

    def test_agent_completion_requires_structured_completed_status(self):
        for name in ("Agent", "Task"):
            self.assert_invalid_agent_statuses(name)

    def assert_invalid_agent_statuses(self, name):
        for metadata in (
            None,
            False,
            0,
            [],
            "completed",
            {},
            {"status": "remote_launched"},
            {"status": "unknown"},
            {"status": None},
            {"status": False},
            {"status": 0},
            {"status": []},
            {"status": {}},
        ):
            messages = agent_run(name)
            messages[2]["tool_use_result"] = metadata
            self.rejected(messages, "agent", agents=True)
        messages = agent_run(name)
        del messages[2]["tool_use_result"]
        self.rejected(messages, "agent", agents=True)

    def test_agent_response_status_controls_completion_despite_input_false(self):
        for name in ("Agent", "Task"):
            messages = agent_run(name)
            messages[1]["message"]["content"][0]["input"]["run_in_background"] = False
            messages[2]["tool_use_result"] = {"status": "async_launched"}
            self.rejected(messages, "agent", agents=True)

    def test_generic_tool_result_does_not_require_agent_status(self):
        messages = agent_run("Read")
        del messages[2]["tool_use_result"]
        result = self.run_gate(messages)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.rejected(messages, "agent", agents=True)

    def test_duplicate_agent_calls_and_results_are_rejected(self):
        for index in (1, 2):
            with self.subTest(index=index):
                messages = agent_run()
                messages.insert(index, copy.deepcopy(messages[index]))
                self.rejected(messages, "tool", agents=True)

    def test_invalid_message_content_or_tool_identity_is_rejected(self):
        for mutate in (
            lambda m: m[1].update(message=None),
            lambda m: m[1]["message"].update(content={}),
            lambda m: m[1]["message"].update(content=[None]),
            lambda m: m[1]["message"]["content"][0].update(id=""),
            lambda m: m[1]["message"]["content"][0].update(name=None),
            lambda m: m[1]["message"]["content"][0].update(input=None),
        ):
            with self.subTest(mutate=mutate):
                messages = agent_run()
                mutate(messages)
                self.rejected(messages, "message")

    def test_malformed_content_block_and_missing_tool_output_are_rejected(self):
        messages = agent_run()
        messages[1]["message"]["content"].append({})
        self.rejected(messages, "message", agents=True)
        messages = agent_run()
        del messages[2]["message"]["content"][0]["content"]
        self.rejected(messages, "tool", agents=True)

    def test_text_messages_are_accepted_without_claiming_agent_execution(self):
        messages = [
            {"type": "user", "message": {"content": "Review this change"}},
            success(),
        ]
        self.assertEqual(self.run_gate(messages).returncode, 0)
        self.rejected(messages, "agent", agents=True)

    def assert_unreadable_path(self, path):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), str(path)],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("read", result.stderr)
        self.assertNotIn("PRIVATE_TOKEN", result.stderr)

    def test_missing_file_directory_and_invalid_encoding_fail_without_leaking_path(
        self,
    ):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            invalid = root / "PRIVATE_TOKEN"
            invalid.write_bytes(b"\xff")
            for path in (root / "missing", root, invalid):
                self.assert_unreadable_path(path)


if __name__ == "__main__":
    unittest.main()
