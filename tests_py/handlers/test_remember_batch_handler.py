"""Actual remember composition with deterministic model/store doubles only."""

from __future__ import annotations

import asyncio
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import Mock, patch

from mcp_server.core import curation, write_gate, write_gate_calibration
from mcp_server.core.capture_template_normalize import capture_template_normalize
from mcp_server.handlers import remember, remember_helpers, remember_preflight
from tests_py.handlers._remember_batch_fakes import BatchStore, blob, make_engine
from tests_py.handlers.test_remember_batch_encoding import scalar_reference


CONTENT = "# Tool: Read\n**Read:** `/same.py`\nshared detail new"


def scenario_fakes(scenario):
    content, neighbors, _action = scenario
    vectors = {content: (1, 0, 0)}
    rows = {}
    for memory_id, text in enumerate(neighbors, 1):
        vectors[capture_template_normalize(text)] = (memory_id, 1, 2)
        rows[memory_id] = {
            "content": text,
            "embedding": blob((1, 0, 0)),
            "created_at": "2026-09-06T00:00:00+00:00",
            "heat": 0.25,
            "compression_level": 0,
        }
        vectors[curation.merge_contents(text, content)] = (1, 0, 0)
    vectors[capture_template_normalize(content)] = (0, 1, 0)
    return BatchStore(content, rows), make_engine(vectors)


def handler_patches(store, engine, action):
    settings = SimpleNamespace(
        WRITE_GATE_THRESHOLD=0.4, WRITE_GATE_HIERARCHICAL=False, SURPRISE_BOOST=0.0
    )
    return [
        (remember, "_get_store", store),
        (remember, "find_exact", None),
        (remember, "get_embedding_engine", engine),
        (remember, "_resolve_domain", "fixture"),
        (remember, "root_agent_topic", None),
        (remember, "get_memory_settings", settings),
        (remember_helpers, "get_memory_settings", settings),
        (remember_preflight, "get_memory_settings", settings),
        (remember, "apply_modulations", {"heat": 1.0}),
        (remember, "update_user_mood_ema", None),
        (remember, "build_merge_response", {"action": "merge"}),
        (write_gate, "_parse_hours_since", 0.0),
        (curation, "decide_curation_action", action),
    ]


class RememberBatchCalls(unittest.TestCase):
    def run_scenario(self, scenario, scalar=False):
        store, engine = scenario_fakes(scenario)
        insert = Mock(return_value={"stored": False, "fixture": True})
        write_gate_calibration.reset_all_states()
        with ExitStack() as stack:
            stack.callback(write_gate_calibration.reset_all_states)
            for module, name, value in handler_patches(store, engine, scenario[2]):
                stack.enter_context(patch.object(module, name, return_value=value))
            stack.enter_context(
                patch.object(remember, "insert_and_post_process", insert)
            )
            if scalar:
                stack.enter_context(
                    patch.object(
                        remember_helpers,
                        "compute_template_normalized_similarities",
                        scalar_reference,
                    )
                )
            result = asyncio.run(
                remember._handler_impl(
                    {
                        "content": scenario[0],
                        "write_class": "deliberate",
                        "is_global": True,
                    }
                )
            )
        return SimpleNamespace(result=result, engine=engine, store=store, insert=insert)

    def test_ordinary_remember_preserves_seven_scalar_calls_and_exact_scores(self):
        neighbors = [f"# Tool: Read\n**Read:** `/neighbor_{n}.py`" for n in range(5)]
        scenario = (CONTENT, neighbors, "create")
        old, new = self.run_scenario(scenario, scalar=True), self.run_scenario(scenario)
        self.assertEqual(old.result, new.result)
        # ObservedNeighbors replaces sims/vec_hits; the store is now at index 13.
        self.assertEqual(old.insert.call_args.args[:13], new.insert.call_args.args[:13])
        self.assertEqual(old.store.searches, new.store.searches)
        self.assertEqual(old.engine.encode.call_count, 7)
        self.assertEqual(
            new.engine.encode.call_args_list, old.engine.encode.call_args_list
        )
        new.engine.encode_batch.assert_not_called()
        self.assertEqual(new.insert.call_args.args[1], blob((1, 0, 0)))
        self.assertNotEqual(new.insert.call_args.args[1], blob((0, 1, 0)))

    def test_merge_equal_to_incoming_content_reuses_raw_vector(self):
        scenario = (CONTENT, [CONTENT.removesuffix(" new")], "merge")
        result = self.run_scenario(scenario)
        self.assertEqual(result.result["action"], "merge")
        self.assertEqual(result.engine.encode.call_count, 3)
        self.assertEqual(result.engine.encode.call_args_list[0].args[0], CONTENT)
        result.engine.encode_batch.assert_not_called()
        result.store.update_memory_compression.assert_called_once_with(
            1, CONTENT, blob((1, 0, 0)), 0
        )
        result.store.update_memory_heat.assert_called_once_with(1, 1.0)
        result.insert.assert_not_called()

    def test_new_concatenation_keeps_necessary_fourth_encode_and_same_merge(self):
        existing = CONTENT.removesuffix(" new") + " old"
        scenario = (CONTENT, [existing], "merge")
        old, new = self.run_scenario(scenario, scalar=True), self.run_scenario(scenario)
        merged = curation.merge_contents(existing, CONTENT)
        self.assertNotEqual(merged, CONTENT)
        self.assertEqual(old.result, new.result)
        self.assertEqual(
            old.store.update_memory_compression.call_args,
            new.store.update_memory_compression.call_args,
        )
        self.assertEqual(
            [call.args[0] for call in new.engine.encode.call_args_list],
            [
                CONTENT,
                capture_template_normalize(CONTENT),
                capture_template_normalize(existing),
                merged,
            ],
        )
        new.engine.encode_batch.assert_not_called()
        self.assertEqual(new.engine.encode.call_count, 4)


if __name__ == "__main__":
    unittest.main()
