"""Composition-root ordering and vector preservation without DB/model effects."""

from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from mcp_server.errors import ValidationError
from mcp_server.handlers import remember, remember_helpers
from mcp_server.core import write_gate, write_gate_calibration
from tests_py.handlers._preflight_fakes import Engine, Store


class HandlerPreflight(unittest.TestCase):
    def setUp(self):
        write_gate_calibration.reset_all_states()
        self.addCleanup(write_gate_calibration.reset_all_states)
        self.store = Store(repeats=10)
        self.engine = Engine()
        self.args = {
            "content": self.store.content,
            "source": "post_tool_capture",
            "write_class": "auto",
            "origin_tool": "Read",
        }
        settings = SimpleNamespace(
            WRITE_GATE_THRESHOLD=0.4, WRITE_GATE_HIERARCHICAL=False, SURPRISE_BOOST=0.0
        )
        mocks = [
            (remember, "_get_store", {"return_value": self.store}),
            (remember, "find_exact", {"return_value": None}),
            (remember, "get_embedding_engine", {"return_value": self.engine}),
            (remember, "_resolve_domain", {"return_value": "fixture"}),
            (remember, "root_agent_topic", {"return_value": None}),
            (remember, "get_memory_settings", {"return_value": settings}),
            (remember_helpers, "get_memory_settings", {"return_value": settings}),
            (write_gate, "_parse_hours_since", {"return_value": 0.0}),
        ]
        self.patches = {}
        for module, name, kwargs in mocks:
            changed = patch.object(module, name, **kwargs)
            self.patches[name] = changed.start()
            self.addCleanup(changed.stop)
        changed = patch(
            "mcp_server.handlers.remember_preflight.get_memory_settings",
            return_value=settings,
        )
        changed.start()
        self.addCleanup(changed.stop)

    def test_bound_rejection_never_constructs_or_calls_encoder(self):
        result = asyncio.run(remember._handler_impl(dict(self.args)))
        self.assertEqual(result["action"], "rejected")
        self.assertIn("novelty_upper_bound", result["novelty"])
        self.patches["get_embedding_engine"].assert_not_called()
        self.assertEqual(self.engine.encoded, [])

    def test_invalid_write_class_fails_before_store_or_model(self):
        with self.assertRaises(ValidationError):
            asyncio.run(remember._handler_impl({**self.args, "write_class": "invalid"}))
        self.patches["_get_store"].assert_not_called()
        self.patches["get_embedding_engine"].assert_not_called()

    def test_supersession_rejection_precedes_preflight_and_model(self):
        rejection = {"stored": False, "action": "rejected", "reason": "missing target"}
        with patch.object(
            remember, "validate_supersede_target", return_value=(None, rejection)
        ):
            with patch.object(remember, "prepare_gate") as preflight:
                result = asyncio.run(remember._handler_impl(dict(self.args)))
        self.assertIs(result, rejection)
        preflight.assert_not_called()
        self.patches["get_embedding_engine"].assert_not_called()

    def test_provenance_resolves_before_preflight(self):
        marker = RuntimeError("stop after provenance")
        seen = []

        def inspect_request(request, observe):
            seen.append((request.options.write_class, request.options.origin))
            raise marker

        with patch.object(remember, "prepare_gate", side_effect=inspect_request):
            for source, tool, expected in (
                ("post_tool_capture", "WebFetch", "network"),
                ("post_tool_capture", "FutureTool", "unknown"),
                ("user", "", "deliberate"),
            ):
                args = {"content": "steady", "source": source, "origin_tool": tool}
                with self.assertRaisesRegex(RuntimeError, "stop after provenance"):
                    asyncio.run(remember._handler_impl(args))
                self.assertEqual(seen[-1][1], expected)
        self.patches["get_embedding_engine"].assert_not_called()

    def test_fallback_keeps_raw_vector_on_actual_insert_boundary(self):
        self.store.repeats = 0
        self.engine.similarity_score = 0.0
        insert = MagicMock(return_value={"stored": False, "fixture": True})
        with patch.object(remember, "apply_modulations", return_value={"heat": 1.0}):
            with patch.object(remember, "try_curation", return_value=("create", None)):
                with patch.object(remember, "insert_and_post_process", insert):
                    args = {**self.args, "is_global": True}
                    asyncio.run(remember._handler_impl(args))
        self.assertEqual(
            insert.call_args.args[1], b"raw:" + self.args["content"].encode()
        )
        self.assertEqual(self.engine.encoded, [self.args["content"]])

    def test_encoder_exception_is_not_swallowed_after_bound_cannot_reject(self):
        self.store.repeats = 0
        failure = RuntimeError("encoder unavailable")
        self.engine.encode = MagicMock(side_effect=failure)
        with self.assertRaisesRegex(RuntimeError, "encoder unavailable") as caught:
            asyncio.run(remember._handler_impl(dict(self.args)))
        self.assertIs(caught.exception, failure)
        self.assertEqual(
            write_gate_calibration.get_state("fixture").total_observations, 0
        )


if __name__ == "__main__":
    unittest.main()
