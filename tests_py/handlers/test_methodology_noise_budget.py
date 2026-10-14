"""Noise parity and large-item preparation, without a model or database."""

from __future__ import annotations

import ast
import asyncio
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from mcp_server.core.response_budget import MAX_RESPONSE_CHARS, serialized_length
from mcp_server.handlers import query_methodology as methodology


def memory(mid, tags, content="useful"):
    return {"id": mid, "content": content, "tags": tags, "heat": 0.9}


class NoiseParity(unittest.TestCase):
    def test_tags_match_the_existing_sqlite_banner_contract(self):
        root = Path(__file__).resolve().parents[2]
        tree = ast.parse(
            (root / "mcp_server/hooks/session_start_sqlite.py").read_text()
        )
        assignment = next(
            node
            for node in tree.body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "_SQLITE_NOISE_TAGS"
                for target in node.targets
            )
        )
        self.assertEqual(
            methodology._CONTEXT_NOISE_TAGS,
            frozenset(ast.literal_eval(assignment.value.args[0])),
        )

    def test_all_retrieval_branches_exclude_only_exact_noise_tags(self):
        rows = [
            memory(1, ["auto-captured"]),
            memory(2, '["memory-replica"]'),
            memory(3, ["archival"]),
            memory(4, ["auto-captured-extra"]),
            memory(5, ["AUTO-CAPTURED"]),
            memory(6, [{}, "memory-replica"]),
        ]
        store = Mock()
        for name in (
            "get_memories_for_domain",
            "get_memories_for_directory",
            "get_hot_memories",
        ):
            getattr(store, name).return_value = rows
        with patch.object(methodology, "_try_get_memory_store", return_value=store):
            for domain, directory in (("d", ""), ("", "/fixture"), ("", "")):
                result = methodology._get_hot_memories(domain, directory)
                self.assertEqual([row["id"] for row in result], [3, 4, 5])

    def test_json_tags_are_lists_and_bad_shapes_do_not_break_useful_rows(self):
        for tags in (None, "bad json", "null", '"auto-captured"', '{"key":1}'):
            self.assertEqual(methodology._normalize_tags(tags), [])
            self.assertFalse(methodology._is_noise_memory(memory(1, tags)))

    def test_selected_noise_rows_are_not_replaced_by_unbounded_refetch(self):
        store = Mock()
        store.get_memories_for_domain.return_value = [memory(1, ["auto-captured"])]
        with patch.object(methodology, "_try_get_memory_store", return_value=store):
            self.assertEqual(methodology._get_hot_memories("d", "", limit=1), [])
        store.get_memories_for_domain.assert_called_once_with(
            "d", min_heat=0.1, limit=1
        )

    def test_real_handler_excludes_noise_before_context_and_preserves_ids(self):
        store = Mock()
        store.get_memories_for_domain.return_value = [
            memory(1, ["auto-captured"], "noisy"),
            memory(2, ["archival"], "curated"),
        ]
        with patch.multiple(
            methodology,
            load_profiles=Mock(return_value={}),
            detect_domain=Mock(return_value={"domain": "d"}),
            _try_get_memory_store=Mock(return_value=store),
            _get_fired_triggers=Mock(return_value=[]),
        ):
            with patch("mcp_server.core.telemetry.record"):
                result = asyncio.run(methodology.handler({"cwd": "/fixture"}))
        self.assertEqual([item["id"] for item in result["hotMemories"]], [2])
        self.assertNotIn("noisy", json.dumps(result))


class LargeItemPreparation(unittest.TestCase):
    def test_62503_character_doc_is_retrievable_when_explicit_budget_truncates(self):
        # source: W4-4 finding, CHANGELOG memory measured at 62,503 characters.
        text = "x" * 62_503
        payload = {"hotMemories": [memory(42, ["documentation"], text)]}
        settings = SimpleNamespace(MAX_RESPONSE_CHARS=len(text))
        with patch.object(methodology, "get_memory_settings", return_value=settings):
            result = methodology._bounded(payload)
        item = result["hotMemories"][0]
        self.assertLessEqual(serialized_length(result), len(text))
        self.assertEqual(item["id"], 42)
        self.assertEqual(item["content_length"], len(text))
        self.assertTrue(item["truncated"])

    def test_default_has_no_measured_per_item_share_yet(self):
        # A passing description of the current limitation, not W4-4 acceptance.
        text = "x" * 62_503
        payload = {"hotMemories": [memory(42, [], text)]}
        settings = SimpleNamespace(MAX_RESPONSE_CHARS=MAX_RESPONSE_CHARS)
        with patch.object(methodology, "get_memory_settings", return_value=settings):
            result = methodology._bounded(payload)
        self.assertEqual(result["hotMemories"][0]["content"], text)


if __name__ == "__main__":
    unittest.main()
