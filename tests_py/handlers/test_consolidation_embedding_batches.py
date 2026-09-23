"""Direct consolidation batches preserve IDs, partial successes and errors."""

from __future__ import annotations

import unittest
from contextlib import nullcontext
from unittest.mock import Mock, call

from mcp_server.handlers.consolidation import cls, embedding_upgrade, sleep
from mcp_server.infrastructure.embedding_batch import encode_items


class Engine:
    mode = "neural"

    def __init__(self):
        self.encode = Mock(side_effect=self.vector)
        self.encode_batch = Mock(
            side_effect=lambda texts: [self.vector(t) for t in texts]
        )

    @staticmethod
    def vector(text):
        return text.encode() if text else None


class UpgradeStore:
    has_vec = True  # source: ADR-1089 — satisfies _FallbackWorklistStore

    def __init__(self, rows):
        self.rows = rows
        self.reembedded = []

    def select_fallback_embeddings(self, limit):
        return self.rows[:limit]

    def reembed_memory(self, memory_id, embedding):
        self.reembedded.append((memory_id, embedding))


class BatchBoundary(unittest.TestCase):
    def test_preserves_input_ids_duplicates_empty_and_missing_fields(self):
        rows = [
            {"id": 9, "text": "a"},
            {"id": 3, "text": ""},
            {"id": 8},
            {"id": 2, "text": "a"},
        ]
        engine = Engine()
        result = encode_items(rows, "text", engine)
        engine.encode_batch.assert_called_once_with(["a", "a"])
        engine.encode.assert_not_called()
        self.assertEqual([row.item["id"] for row in result], [9, 3, 8, 2])
        self.assertEqual(
            [result[index].value() for index in (0, 1, 3)], [b"a", None, b"a"]
        )
        with self.assertRaises(KeyError):
            result[2].value()

    def test_batch_failure_logs_then_recovers_independent_scalar_successes(self):
        engine = Engine()
        engine.encode_batch.side_effect = RuntimeError("whole batch")
        engine.encode.side_effect = [b"first", ValueError("one item"), b"last"]
        rows = [{"text": text} for text in ["first", "bad", "last"]]
        with self.assertLogs(
            "mcp_server.infrastructure.embedding_batch", level="ERROR"
        ) as logs:
            result = encode_items(rows, "text", engine)
        self.assertIn("retrying each item", logs.output[0])
        self.assertEqual(result[0].value(), b"first")
        self.assertEqual(result[2].value(), b"last")
        with self.assertRaisesRegex(ValueError, "one item"):
            result[1].value()
        self.assertEqual(engine.encode.call_count, 3)

    def test_empty_worklist_or_only_empty_content_never_calls_encoder(self):
        engine = Engine()
        self.assertEqual(encode_items([], "text", engine), [])
        self.assertIsNone(encode_items([{"text": ""}], "text", engine)[0].value())
        engine.encode.assert_not_called()
        engine.encode_batch.assert_not_called()

    def test_malformed_batch_length_retries_without_wrong_id_alignment(self):
        engine = Engine()
        engine.encode_batch.return_value = [b"wrong"]
        engine.encode_batch.side_effect = None
        with self.assertLogs(
            "mcp_server.infrastructure.embedding_batch", level="ERROR"
        ):
            result = encode_items([{"text": "a"}, {"text": "b"}], "text", engine)
        self.assertEqual([item.value() for item in result], [b"a", b"b"])


class DirectWriters(unittest.TestCase):
    def test_replay_keeps_order_none_and_partial_storage_failure(self):
        engine, store = Engine(), Mock()
        store.update_memory_compression.side_effect = [
            None,
            RuntimeError("write"),
            None,
        ]
        rows = [
            {"memory_id": mid, "enriched_content": text}
            for mid, text in [(7, "a"), (2, "bad"), (5, "")]
        ]
        with self.assertLogs(sleep.logger, level="ERROR"):
            actual = sleep._apply_dream_replay(store, engine, rows)
        self.assertEqual(actual, [7, 5])
        self.assertEqual(
            [call.args[:3] for call in store.update_memory_compression.call_args_list],
            [(7, "a", b"a"), (2, "bad", b"bad"), (5, "", None)],
        )
        engine.encode_batch.assert_not_called()
        self.assertEqual(
            engine.encode.call_args_list, [call(text) for text in ["a", "bad", ""]]
        )

    def test_stale_updates_keep_id_vector_pairs_and_skip_empty(self):
        engine, store, conn = Engine(), Mock(), Mock()
        store.acquire_batch.return_value = nullcontext(conn)
        rows = [
            {"memory_id": mid, "content": text}
            for mid, text in [(7, "b"), (2, ""), (5, "a")]
        ]
        self.assertEqual(sleep._fix_stale_embeddings(store, engine, rows), 2)
        self.assertEqual(
            [call.args[1] for call in conn.execute.call_args_list],
            [(b"b", 7), (b"a", 5)],
        )
        engine.encode_batch.assert_not_called()
        self.assertEqual(
            engine.encode.call_args_list, [call(text) for text in ["b", "a"]]
        )

    def test_upgrade_worklist_preserves_scalar_calls_and_existing_guards(self):
        engine = Engine()
        store = UpgradeStore(
            [
                {"memory_id": 7, "content": "a"},
                {"memory_id": 2, "content": ""},
                {"memory_id": 3, "content": "b"},
            ]
        )
        self.assertEqual(
            embedding_upgrade.run_embedding_upgrade_cycle(store, engine),
            {"upgraded": 2},
        )
        self.assertEqual(store.reembedded, [(7, b"a"), (3, b"b")])
        engine.encode_batch.assert_not_called()
        self.assertEqual(
            engine.encode.call_args_list, [call(text) for text in ["a", "b"]]
        )
        engine.encode_batch.reset_mock()
        engine.mode = "fallback"
        self.assertIn(
            "reason", embedding_upgrade.run_embedding_upgrade_cycle(store, engine)
        )
        engine.encode_batch.assert_not_called()

    def test_cls_keeps_provenance_and_counts_only_successful_rows(self):
        engine, store = Engine(), Mock()
        store.insert_memory.side_effect = [RuntimeError("write"), None]
        plan = {
            "new_semantics": [
                {"schema": "a", "tags": ["first"], "source_memory_ids": [7]},
                {
                    "schema": "b",
                    "tags": ["second"],
                    "source_memory_ids": [2],
                    "confabulation_risk": True,
                },
            ]
        }
        with self.assertLogs(cls.logger, level="ERROR"):
            self.assertEqual(cls._create_semantic_memories(store, engine, plan), 1)
        rows = [call.args[0] for call in store.insert_memory.call_args_list]
        self.assertEqual([row["embedding"] for row in rows], [b"a", b"b"])
        self.assertIn("derived-src:7", rows[0]["tags"])
        self.assertIn("confabulation-risk", rows[1]["tags"])
        engine.encode_batch.assert_not_called()
        self.assertEqual(
            engine.encode.call_args_list, [call(text) for text in ["a", "b"]]
        )

    def test_all_empty_direct_worklists_have_no_encoding(self):
        engine, store = Engine(), Mock()
        store.acquire_batch.return_value = nullcontext(Mock())
        self.assertEqual(sleep._apply_dream_replay(store, engine, []), [])
        self.assertEqual(sleep._fix_stale_embeddings(store, engine, []), 0)
        self.assertEqual(
            cls._create_semantic_memories(store, engine, {"new_semantics": []}), 0
        )
        self.assertEqual(
            embedding_upgrade.run_embedding_upgrade_cycle(UpgradeStore([]), engine),
            {"upgraded": 0},
        )
        engine.encode.assert_not_called()
        engine.encode_batch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
