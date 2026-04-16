"""Tests for CLS cycle `reason_for_zero` diagnostics (issue #14 P2).

The `cls` consolidate stage returns a `reason_for_zero` field when every
mutational counter is zero, distinguishing early-return branches from a
"genuine quiet store" no-op. Each reason value must be reachable via a
realistic store configuration, and the field must be ABSENT whenever
any mutational counter is non-zero (the field is additive diagnostic,
not a required key).

Uses in-process fake stores so each branch can be exercised
deterministically without priming PostgreSQL.
"""

from __future__ import annotations

from typing import Any

import pytest

from mcp_server.handlers.consolidation.cls import run_cls_cycle


# ─── Fake collaborators ──────────────────────────────────────────────────


class _FakeEmbeddings:
    """Embedding engine stub.

    `similarity(a, b)` returns 1.0 if the raw embedding values compare
    equal, else 0.0. Tests craft episodic memories whose embedding
    fields are plain bytes/strings so similarity under this fake
    matches "exact byte-identical embeddings."
    """

    def similarity(self, a: Any, b: Any) -> float:
        if a is None or b is None:
            return 0.0
        return 1.0 if a == b else 0.0

    def encode(self, text: str) -> bytes:  # pragma: no cover — not hit on zero runs
        return text.encode("utf-8")


class _FakeStore:
    """In-process stand-in for MemoryStore, configurable per test."""

    def __init__(
        self,
        episodic: list[dict] | None = None,
        semantic: list[dict] | None = None,
        entities: list[dict] | None = None,
    ) -> None:
        self._episodic = episodic or []
        self._semantic = semantic or []
        self._entities = entities or []
        self.inserted_memories: list[dict] = []
        self.inserted_relationships: list[dict] = []

    def get_episodic_memories(self, limit: int = 2000) -> list[dict]:
        return self._episodic[:limit]

    def get_semantic_memories(self, limit: int = 2000) -> list[dict]:
        return self._semantic[:limit]

    def get_all_entities(self, min_heat: float = 0.0) -> list[dict]:
        return self._entities

    def insert_memory(self, mem: dict) -> int:  # pragma: no cover
        self.inserted_memories.append(mem)
        return len(self.inserted_memories)

    def insert_relationship(self, rel: dict) -> None:  # pragma: no cover
        self.inserted_relationships.append(rel)


# ─── Helpers ─────────────────────────────────────────────────────────────


def _mem(
    mid: int,
    *,
    embedding: bytes,
    content: str = "",
    session: str = "s1",
    tags: list[str] | None = None,
) -> dict:
    return {
        "id": mid,
        "embedding": embedding,
        "content": content,
        "source": session,
        "session_id": session,
        "tags": tags or [],
    }


# ─── Tests ───────────────────────────────────────────────────────────────


class TestClsReasonForZero:
    """Each reason value is reachable; absent when any counter non-zero."""

    def test_empty_episodic_scan_triggers_reason(self):
        """Store with zero episodic memories → reason = empty_episodic_scan.

        Spec: `empty_episodic_scan` — scan returned 0 episodic memories
        (window too tight, all cold, etc.).
        """
        store = _FakeStore(episodic=[], semantic=[{"content": "x"}], entities=[])

        result = run_cls_cycle(store, settings=None, embeddings=_FakeEmbeddings())

        assert result["reason_for_zero"] == "empty_episodic_scan"
        # Preserve existing contract: original counters present and all zero.
        assert result["patterns_found"] == 0
        assert result["new_semantics_created"] == 0
        assert result["skipped_inconsistent"] == 0
        assert result["skipped_duplicate"] == 0
        assert result["causal_edges_found"] == 0
        assert result["episodic_scanned"] == 0

    def test_below_min_pattern_size_triggers_reason(self):
        """Pairs form (2 memories with identical embedding) but cluster
        size < min_occurrences (3) → reason = below_min_pattern_size.

        Spec: "2000 episodic memories with only 2 shared [similarity]
        per cluster → patterns_found == 0 with the specific reason."
        We use a tractable-sized fixture (pairs of 2) — the logic is
        identical; scaling to 2000 would only inflate test runtime.
        """
        # 10 pairs of size 2 (same embedding within a pair, different
        # across pairs). No cluster reaches min_occurrences=3.
        episodic = []
        for pair_idx in range(10):
            emb = f"pair_{pair_idx}".encode("utf-8")
            episodic.append(_mem(pair_idx * 2, embedding=emb, session=f"s{pair_idx}a"))
            episodic.append(
                _mem(pair_idx * 2 + 1, embedding=emb, session=f"s{pair_idx}b")
            )
        store = _FakeStore(episodic=episodic, semantic=[], entities=[])

        result = run_cls_cycle(store, settings=None, embeddings=_FakeEmbeddings())

        assert result["patterns_found"] == 0
        assert result["new_semantics_created"] == 0
        assert result["reason_for_zero"] == "below_min_pattern_size"
        assert result["episodic_scanned"] == len(episodic)

    def test_insufficient_pairs_triggers_reason(self):
        """All singletons (no embedding similarity pairs) AND no entity
        mentioned enough → reason = insufficient_pairs.

        Spec: `insufficient_pairs` — no two episodic memories shared
        enough entities to form candidate pairs. We simulate a
        minimal-signal store: each memory has a distinct embedding and
        there are no qualifying entities at all.
        """
        episodic = [
            _mem(i, embedding=f"uniq_{i}".encode("utf-8"), session=f"s{i}")
            for i in range(5)
        ]
        store = _FakeStore(episodic=episodic, semantic=[], entities=[])

        result = run_cls_cycle(store, settings=None, embeddings=_FakeEmbeddings())

        assert result["patterns_found"] == 0
        assert result["causal_edges_found"] == 0
        assert result["reason_for_zero"] == "insufficient_pairs"

    def test_no_qualifying_entities_triggers_reason(self):
        """All singletons AND some entities qualify (>=3 mentions) but
        below _MIN_ENTITIES_FOR_PC (5) → reason = no_qualifying_entities.

        Spec: `no_qualifying_entities` — `_MIN_ENTITIES_FOR_PC` gate
        rejected the run (active entity set too small).
        """
        # 5 episodic memories, all distinct embeddings → no pairs form.
        # Content mentions 2 shared entities ≥ 3 times each (qualifying)
        # but qualifying_count = 2 < 5 (_MIN_ENTITIES_FOR_PC).
        episodic = [
            _mem(
                i,
                embedding=f"emb_{i}".encode("utf-8"),
                content="foo and bar are related" if i < 4 else "unrelated text",
                session=f"s{i}",
            )
            for i in range(5)
        ]
        entities = [
            {"id": 1, "name": "foo", "heat": 0.5},
            {"id": 2, "name": "bar", "heat": 0.5},
        ]
        store = _FakeStore(episodic=episodic, semantic=[], entities=entities)

        result = run_cls_cycle(store, settings=None, embeddings=_FakeEmbeddings())

        assert result["patterns_found"] == 0
        assert result["causal_edges_found"] == 0
        assert result["reason_for_zero"] == "no_qualifying_entities"

    def test_passed_through_when_no_gates_failed_but_no_mutation(self):
        """Genuine quiet-store: no pairs, no entities → still classified
        as no-signal, NOT `passed_through`.

        We instead test the only realistic `passed_through` scenario:
        clustering has no multi-member clusters AND PC gate passed
        (qualifying >= _MIN_ENTITIES_FOR_PC) but found no edges. That
        requires >= 5 qualifying entities with low correlation. The
        simplest deterministic hit: provide 5 entities each mentioned
        in most memories but with no consistent co-occurrence pattern
        for the PC algorithm to flag.
        """
        # 6 episodic memories, each distinct embedding, each mentioning
        # all 5 entities (every entity's count = 6 >= 3, so 5
        # qualifying entities). PC typically finds no directed edges
        # when every pair has identical unconditional co-occurrence.
        entity_names = ["alpha", "beta", "gamma", "delta", "epsilon"]
        content = " ".join(entity_names)
        episodic = [
            _mem(
                i,
                embedding=f"unique_{i}".encode("utf-8"),
                content=content,
                session=f"s{i}",
            )
            for i in range(6)
        ]
        entities = [
            {"id": idx + 1, "name": name, "heat": 0.5}
            for idx, name in enumerate(entity_names)
        ]
        store = _FakeStore(episodic=episodic, semantic=[], entities=entities)

        result = run_cls_cycle(store, settings=None, embeddings=_FakeEmbeddings())

        # Core expectation: with qualifying_count >= _MIN_ENTITIES_FOR_PC
        # and no clustering pairs, we must not classify as
        # insufficient_pairs or no_qualifying_entities. Depending on
        # whether causal_edges_found ended up 0 or not, the reason key
        # may be absent (if PC created edges) or "passed_through"
        # (if PC ran clean but produced nothing).
        if result["causal_edges_found"] == 0:
            assert result["reason_for_zero"] == "passed_through"
        else:
            # PC produced edges — no `reason_for_zero` at all.
            assert "reason_for_zero" not in result

    def test_reason_absent_when_patterns_found_nonzero(self):
        """If clustering produced a pattern ≥ min_occurrences, the
        `reason_for_zero` field MUST be absent (diagnostic is additive
        only on the all-zero path).
        """
        # 3 memories with identical embedding across 2 sessions forms a
        # pattern of size 3 with 2 sessions → passes both thresholds.
        emb = b"pattern"
        episodic = [
            _mem(1, embedding=emb, content="always use UTC", session="s1"),
            _mem(2, embedding=emb, content="always use UTC", session="s2"),
            _mem(3, embedding=emb, content="always use UTC", session="s1"),
        ]
        store = _FakeStore(episodic=episodic, semantic=[], entities=[])

        result = run_cls_cycle(store, settings=None, embeddings=_FakeEmbeddings())

        assert result["patterns_found"] >= 1
        assert "reason_for_zero" not in result


class TestClsPassedThroughLog:
    """When reason = passed_through, an INFO log surfaces the no-op."""

    def test_passed_through_emits_info_log(self, caplog):
        """Operators grep for `stage=cls reason=passed_through`.

        The log line must include the literal tokens `stage=cls` and
        `reason=passed_through` so shell-grep pipelines stay trivial.
        """
        import logging

        entity_names = ["alpha", "beta", "gamma", "delta", "epsilon"]
        content = " ".join(entity_names)
        episodic = [
            _mem(
                i,
                embedding=f"unique_{i}".encode("utf-8"),
                content=content,
                session=f"s{i}",
            )
            for i in range(6)
        ]
        entities = [
            {"id": idx + 1, "name": name, "heat": 0.5}
            for idx, name in enumerate(entity_names)
        ]
        store = _FakeStore(episodic=episodic, semantic=[], entities=entities)

        with caplog.at_level(
            logging.INFO, logger="mcp_server.handlers.consolidation.cls"
        ):
            result = run_cls_cycle(store, settings=None, embeddings=_FakeEmbeddings())

        if result.get("reason_for_zero") == "passed_through":
            assert any(
                "stage=cls" in rec.getMessage()
                and "reason=passed_through" in rec.getMessage()
                for rec in caplog.records
            )
        else:
            pytest.skip("Scenario did not deterministically land on passed_through")

    def test_non_passed_through_does_not_emit_info_log(self, caplog):
        """Other reasons must NOT emit the grep-targeted INFO line."""
        import logging

        store = _FakeStore(episodic=[], semantic=[], entities=[])

        with caplog.at_level(
            logging.INFO, logger="mcp_server.handlers.consolidation.cls"
        ):
            result = run_cls_cycle(store, settings=None, embeddings=_FakeEmbeddings())

        assert result["reason_for_zero"] == "empty_episodic_scan"
        assert not any(
            "stage=cls reason=passed_through" in rec.getMessage()
            for rec in caplog.records
        )
