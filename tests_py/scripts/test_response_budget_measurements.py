"""Pure capture/ratio tests; fixture numbers are not runtime calibration data."""

from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch
from urllib.parse import quote

from scripts import collect_response_budget_payloads as collect
from scripts import response_budget_measurements as measure


class Observations(unittest.TestCase):
    def test_utf16_and_js_rounding_differ_from_python_codepoints_and_round(self):
        result = measure.text_observation([{"type": "text", "text": "😀"}])
        self.assertEqual(result["text_code_points"], 1)
        self.assertEqual(result["text_utf16_units"], 2)
        self.assertEqual(result["text_utf8_bytes"], 4)
        self.assertEqual(result["host_estimated_tokens"], 1)

    def test_estimate_never_becomes_an_observed_token_count(self):
        row = {
            "tool": "recall",
            "request_sha256": "request",
            "result": {"content": [{"type": "text", "text": "data"}]},
        }
        report = measure.summarize([row], {})
        self.assertIn("pending", report["token_calibration"]["status"])
        self.assertNotIn("input_tokens", json.dumps(report))

    def test_provider_evidence_requires_matching_digest_model_and_api_method(self):
        content = [{"type": "text", "text": "data"}]
        digest = measure.content_digest(content)
        record = {
            "content_sha256": digest,
            "input_tokens": 2,
            "method": "messages.countTokens",
            "model": "fixture",
            "source": "unit-test-double",
        }
        indexed = measure.token_observations([record])
        rows = [
            {
                "tool": "recall",
                "request_sha256": "request",
                "result": {"content": content},
            }
        ]
        report = measure.summarize(rows, indexed)
        self.assertEqual(
            report["token_calibration"]["utf16_units_per_input_token"]["min"], 2
        )
        self.assertIsNone(report["token_calibration"]["budget_recommendation"])
        with self.assertRaises(ValueError):
            measure.summarize(rows, {"wrong": record})
        with self.assertRaises(ValueError):
            measure.token_observations([{**record, "method": "tiktoken"}])
        with self.assertRaises(ValueError):
            measure.token_observations(
                [record, {**record, "content_sha256": "other", "model": "other"}]
            )

    def test_nontext_content_is_not_silently_counted_as_text(self):
        with self.assertRaises(ValueError):
            measure.text_observation([{"type": "image", "data": "fixture"}])

    def test_actual_sdk_wire_units_can_exceed_the_legacy_compact_budget(self):
        from mcp.server.mcpserver.utilities.func_metadata import _convert_to_content
        from mcp_server.core.response_budget import (
            HOST_CAP_CHARS,
            MAX_RESPONSE_CHARS,
            serialized_length,
        )

        # Synthetic Unicode counterexample, not a sampled production payload.
        payload = {"content": "😀" * 62_503}
        blocks = [
            block.model_dump(mode="json", exclude_none=True)
            for block in _convert_to_content(payload)
        ]
        self.assertLess(serialized_length(payload), MAX_RESPONSE_CHARS)
        self.assertGreater(
            measure.text_observation(blocks)["text_utf16_units"], HOST_CAP_CHARS
        )


class Collector(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()

    def environment(self):
        socket = quote(str(self.root / "no-postgres"), safe="")
        return {
            "CORTEX_CLAUDE_DIR": str(self.root / "claude"),
            "DATABASE_URL": f"postgresql://{socket}/cortex_budget_fixture",
            "CORTEX_MEMORY_DATABASE_URL": f"postgresql://{socket}/cortex_budget_fixture",
            "CORTEX_MEMORY_STORE_BACKEND": "sqlite",
            "CORTEX_EMBEDDING_ZERO_DOWNLOAD": "1",
            # Path.home() needs HOME on POSIX and USERPROFILE on Windows; an
            # environment cleared of both cannot name a home on Windows.
            "HOME": str(self.root / "home"),
            "USERPROFILE": str(self.root / "home"),
        }

    def test_environment_requires_explicit_isolation_before_runtime_import(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(ValueError):
                collect.validate_environment(self.root)
        with patch.dict("os.environ", self.environment(), clear=True):
            collect.validate_environment(self.root)
            (self.root / "no-postgres").mkdir()
            with self.assertRaises(ValueError):
                collect.validate_environment(self.root)

    def test_case_count_and_tool_allowlist_are_explicit(self):
        case = {"tool": "recall", "arguments": {"query": "fixture"}}
        collect.validate_cases([case], expected=1)
        with self.assertRaises(ValueError):
            collect.validate_cases([case])
        with self.assertRaises(ValueError):
            collect.validate_cases([{**case, "tool": "remember"}], expected=1)

    def test_capture_digest_must_match_the_request_manifest(self):
        case = {"tool": "recall", "arguments": {"query": "fixture"}}
        record = {"tool": "recall", "request_sha256": collect.request_digest(case)}
        collect.validate_captures([case], [record])
        with self.assertRaises(ValueError):
            collect.validate_captures([case], [{**record, "request_sha256": "wrong"}])
        with self.assertRaises(ValueError):
            collect.validate_captures([case], [])

    def test_capture_uses_runtime_results_and_never_overwrites_prior_capture(self):
        wire = {"content": [{"type": "text", "text": "runtime result"}]}
        server = Mock(
            call_tool=AsyncMock(return_value=Mock(model_dump=Mock(return_value=wire)))
        )
        cases = [{"tool": "recall", "arguments": {"query": "fixture"}}]
        output = self.root / "responses.jsonl"
        rows = asyncio.run(
            collect.capture(server, cases, output, {"source": "fixture"})
        )
        server.call_tool.assert_awaited_once_with("recall", {"query": "fixture"})
        self.assertEqual(rows[0]["result"], wire)
        self.assertEqual(measure.read_jsonl(output), rows)
        self.assertEqual(collect.capture_provenance(rows), {"source": "fixture"})
        with self.assertRaises(ValueError):
            collect.capture_provenance([rows[0], {**rows[0], "capture_provenance": {}}])
        with self.assertRaises(FileExistsError):
            asyncio.run(collect.capture(server, cases, output, {"source": "fixture"}))

    def test_owned_stores_close_when_capture_fails(self):
        close = Mock()
        with patch.object(collect, "load_runtime", return_value=(Mock(), close)):
            with patch.object(collect, "capture", side_effect=RuntimeError("fixture")):
                with self.assertRaises(RuntimeError):
                    asyncio.run(collect.collect(self.root, [], self.root / "out", {}))
        close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
