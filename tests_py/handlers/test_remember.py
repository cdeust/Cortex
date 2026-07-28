"""Tests for mcp_server.handlers.remember — store memory handler."""

import asyncio
import os

import pytest

from mcp_server.handlers.remember import handler
from mcp_server.handlers.remember_helpers import (
    MOOD_EMA_ALPHA,
    update_user_mood_ema,
)
from mcp_server.shared.vader import vader_compound


class TestRememberHandler:
    def test_no_content_returns_not_stored(self):
        result = asyncio.run(handler(None))
        assert result["stored"] is False
        assert result["reason"] == "no_content"

    def test_empty_content_returns_not_stored(self):
        result = asyncio.run(handler({"content": ""}))
        assert result["stored"] is False

    def test_store_with_force(self):
        result = asyncio.run(
            handler(
                {
                    "content": "Force stored memory for testing",
                    "force": True,
                    "tags": ["test"],
                }
            )
        )
        assert result["stored"] is True
        assert result["memory_id"] > 0
        assert result["reason"] == "forced"
        assert "heat" in result
        assert "novelty" in result
        assert "importance" in result

    def test_error_content_bypasses_gate(self):
        result = asyncio.run(
            handler(
                {
                    "content": "RuntimeError: connection refused. "
                    "The server crashed with a traceback.",
                }
            )
        )
        assert result["stored"] is True
        assert result["reason"] == "bypass_error"

    def test_decision_content_bypasses_gate(self):
        result = asyncio.run(
            handler(
                {
                    "content": "We decided to migrate from MySQL "
                    "to PostgreSQL for the new project.",
                }
            )
        )
        assert result["stored"] is True
        assert result["reason"] == "bypass_decision"

    def test_important_tag_bypasses_gate(self):
        result = asyncio.run(
            handler(
                {
                    "content": "Something mildly interesting happened today",
                    "tags": ["important"],
                }
            )
        )
        assert result["stored"] is True
        assert result["reason"] == "bypass_important_tag"

    def test_prospective_triggers_extracted(self):
        result = asyncio.run(
            handler(
                {
                    "content": "TODO: fix the parser before release. "
                    "Remember to update docs.",
                    "force": True,
                }
            )
        )
        assert result["stored"] is True
        assert len(result["triggers_created"]) >= 1

    def test_domain_auto_detection(self):
        result = asyncio.run(
            handler(
                {
                    "content": "Important architecture decision for the project",
                    "directory": "/tmp/fake-project",
                    "force": True,
                }
            )
        )
        assert result["stored"] is True
        # domain may be empty if no profile exists, but shouldn't error
        assert "domain" in result

    def test_store_global_memory(self):
        result = asyncio.run(
            handler(
                {
                    "content": "Global infra: Postgres at 10.0.1.50:5432 user cortex",
                    "force": True,
                    "tags": ["infrastructure"],
                    "is_global": True,
                }
            )
        )
        assert result["stored"] is True
        mem_id = result["memory_id"]

        from mcp_server.infrastructure.memory_config import get_memory_settings
        from mcp_server.infrastructure.memory_store import get_shared_store

        s = get_memory_settings()
        store = get_shared_store(s.DB_PATH, s.EMBEDDING_DIM)
        mem = store.get_memory(mem_id)
        assert mem is not None
        assert mem.get("is_global") is True or mem.get("is_global") == 1

    def test_response_shape(self):
        result = asyncio.run(
            handler(
                {
                    "content": "Shape test content with error keyword "
                    "to ensure storage",
                    "force": True,
                }
            )
        )
        assert isinstance(result["stored"], bool)
        if result["stored"]:
            assert isinstance(result["memory_id"], int)
            assert isinstance(result["heat"], float)
            assert isinstance(result["novelty"], dict)
            assert isinstance(result["importance"], float)
            assert isinstance(result["valence"], float)
            assert isinstance(result["reason"], str)
            assert isinstance(result["triggers_created"], list)


class TestRememberWriteClass:
    """M-D2 (7.4): explicit write_class argument — validation, resolution,
    and persistence through the real store (no DB stub needed; force=True
    matches the existing store-hitting test style above)."""

    def test_invalid_write_class_raises_validation_error(self):
        from mcp_server.errors import ValidationError

        with pytest.raises(ValidationError, match="not-a-real-class"):
            asyncio.run(
                handler(
                    {
                        "content": "Invalid write_class should be rejected",
                        "write_class": "not-a-real-class",
                        "force": True,
                    }
                )
            )

    def test_explicit_deliberate_is_persisted(self):
        result = asyncio.run(
            handler(
                {
                    "content": "Explicit deliberate write_class round-trip test",
                    "write_class": "deliberate",
                    "force": True,
                }
            )
        )
        assert result["stored"] is True
        assert result["write_class"] == "deliberate"

        from mcp_server.infrastructure.memory_config import get_memory_settings
        from mcp_server.infrastructure.memory_store import get_shared_store

        s = get_memory_settings()
        store = get_shared_store(s.DB_PATH, s.EMBEDDING_DIM)
        mem = store.get_memory(result["memory_id"])
        assert mem is not None
        assert mem.get("write_class") == "deliberate"

    def test_explicit_mechanical_is_persisted(self):
        result = asyncio.run(
            handler(
                {
                    "content": "Explicit mechanical write_class round-trip test",
                    "write_class": "mechanical",
                    "source": "ingest_codebase",
                    "force": True,
                }
            )
        )
        assert result["stored"] is True
        assert result["write_class"] == "mechanical"

    def test_omitted_write_class_falls_back_to_source_deliberate(self):
        result = asyncio.run(
            handler(
                {
                    "content": "Omitted write_class falls back via source inference",
                    "source": "some-future-source-kind",
                    "force": True,
                }
            )
        )
        assert result["stored"] is True
        assert result["write_class"] == "deliberate"

    def test_omitted_write_class_falls_back_to_source_auto(self):
        result = asyncio.run(
            handler(
                {
                    "content": "Omitted write_class falls back to auto via source",
                    "source": "post_tool_capture",
                    "force": True,
                }
            )
        )
        assert result["stored"] is True
        assert result["write_class"] == "auto"

    def test_none_content_write_class_error_takes_precedence_is_irrelevant(self):
        """No-content rejection happens before write_class validation —
        pinning the existing early-return order (unaffected by 7.4)."""
        result = asyncio.run(handler({"write_class": "not-a-real-class"}))
        assert result["stored"] is False
        assert result["reason"] == "no_content"


class _MoodStoreStub:
    """Minimal duck-typed user_mood store for EMA hook tests.

    Mirrors PgMemoryStore.get_user_mood / set_user_mood semantics without
    requiring a live PG connection. Returns None when absent (matches the
    'no row' branch of the real store).
    """

    def __init__(self, initial: float | None = None) -> None:
        self.valence: float | None = initial
        self.write_calls: int = 0

    def get_user_mood(self) -> float | None:
        return self.valence

    def set_user_mood(self, valence: float, arousal: float = 0.0) -> None:
        self.write_calls += 1
        self.valence = max(-1.0, min(1.0, float(valence)))


class TestUserMoodEmaHook:
    """update_user_mood_ema unit tests — stub store, no DB required."""

    def test_positive_message_increases_mood(self):
        store = _MoodStoreStub(initial=0.0)
        new = update_user_mood_ema(
            "This is wonderful, I am so happy and delighted!",
            source="user",
            store=store,
        )
        assert new is not None
        assert new > 0.0
        # First update from 0.0 baseline: new = α * compound
        compound = vader_compound("This is wonderful, I am so happy and delighted!")
        assert new == pytest.approx(MOOD_EMA_ALPHA * compound, rel=1e-6)
        assert store.valence == pytest.approx(new, rel=1e-6)
        assert store.write_calls == 1

    def test_negative_message_decreases_mood(self):
        store = _MoodStoreStub(initial=0.0)
        new = update_user_mood_ema(
            "This is terrible, I hate this awful broken mess.",
            source="user",
            store=store,
        )
        assert new is not None
        assert new < 0.0
        assert store.write_calls == 1

    def test_neutral_message_keeps_mood_near_baseline(self):
        store = _MoodStoreStub(initial=0.0)
        new = update_user_mood_ema(
            "The file is at /tmp/foo.txt with 42 bytes.",
            source="user",
            store=store,
        )
        assert new is not None
        assert abs(new) < 0.1
        assert store.write_calls == 1

    def test_ema_decay_pulls_toward_new_signal(self):
        """A negative message after a positive baseline must decay toward 0."""
        store = _MoodStoreStub(initial=0.6)
        new = update_user_mood_ema(
            "This is terrible, awful, broken garbage.",
            source="user",
            store=store,
        )
        assert new is not None
        # EMA: new = (1-α)*0.6 + α*compound; compound is negative, so new < 0.6
        assert new < 0.6
        # And the write happened
        assert store.write_calls == 1

    def test_non_user_source_skipped(self):
        for source in ("tool", "consolidation", "import", "session"):
            store = _MoodStoreStub(initial=0.0)
            new = update_user_mood_ema(
                "This is wonderful and amazing!",
                source=source,
                store=store,
            )
            assert new is None, f"source={source} should not update mood"
            assert store.write_calls == 0
            assert store.valence == 0.0

    def test_ablation_skips_write(self):
        store = _MoodStoreStub(initial=0.0)
        prev = os.environ.get("CORTEX_ABLATE_MOOD_CONGRUENT_RERANK")
        os.environ["CORTEX_ABLATE_MOOD_CONGRUENT_RERANK"] = "1"
        try:
            new = update_user_mood_ema(
                "Wonderful happy joyful day!",
                source="user",
                store=store,
            )
        finally:
            if prev is None:
                os.environ.pop("CORTEX_ABLATE_MOOD_CONGRUENT_RERANK", None)
            else:
                os.environ["CORTEX_ABLATE_MOOD_CONGRUENT_RERANK"] = prev
        assert new is None
        assert store.write_calls == 0

    def test_store_without_api_returns_none(self):
        class _NoApi:
            pass

        new = update_user_mood_ema("Anything here.", source="user", store=_NoApi())
        assert new is None

    def test_store_failure_swallowed(self):
        class _Boom:
            def get_user_mood(self) -> float | None:
                return 0.0

            def set_user_mood(self, *a, **k) -> None:
                raise RuntimeError("db down")

        # Must not raise
        new = update_user_mood_ema("Happy day!", source="user", store=_Boom())
        assert new is None

    def test_no_baseline_treats_old_as_zero(self):
        store = _MoodStoreStub(initial=None)  # no row yet
        new = update_user_mood_ema("Wonderful!", source="user", store=store)
        assert new is not None
        # Old None → treated as 0.0; new = α * compound
        compound = vader_compound("Wonderful!")
        assert new == pytest.approx(MOOD_EMA_ALPHA * compound, rel=1e-6)


# ── Issue #17 — handler returns dict, not str ─────────────────────────────


class TestRememberReturnsDict:
    """Liskov: remember handler must return a dict per its output_schema.

    PSGSupport reported strict MCP clients (Claude Code tool runtime)
    rejecting the response with ``structured_content must be a dict or
    None. Got str``. Root cause was ``safe_handler`` JSON-encoding the
    dict before returning. The contract is dict; this test pins it.
    """

    def test_handler_direct_returns_dict(self):
        result = asyncio.run(handler(None))
        assert isinstance(result, dict)

    def test_safe_handler_returns_dict(self):
        from mcp_server.tool_error_handler import safe_handler

        result = asyncio.run(
            safe_handler(handler, {"content": ""}, tool_name="remember")
        )
        assert isinstance(result, dict)
        assert not isinstance(result, str)


class _CurationFakeEngine:
    """Minimal embedding engine: fixed high similarity, real encode noop."""

    def similarity(self, _a, _b) -> float:
        return 0.95

    def encode(self, _text):
        return [0.0]


class _CurationFakeStore:
    """Fake store exposing only what try_curation touches."""

    def __init__(self, cand: dict) -> None:
        self._cand = cand
        self.merged = False

    def search_vectors(self, _embedding, top_k=3, min_heat=0.0):
        return [(self._cand["id"], 0.05)]

    def get_memory(self, mem_id):
        return self._cand if mem_id == self._cand["id"] else None

    def update_memory_compression(self, *_a, **_k):
        self.merged = True

    def update_memory_heat(self, *_a, **_k):
        pass


class TestTryCurationSupersede:
    """Phase 2 write-path: contradiction routes merge → supersede."""

    def _run(self, new_content: str, existing_content: str):
        from mcp_server.handlers.remember_helpers import try_curation

        cand = {"id": 42, "content": existing_content, "embedding": [0.1]}
        store = _CurationFakeStore(cand)
        action, mid = try_curation(
            content=new_content,
            embedding=[0.1],
            force=False,
            store=store,
            emb_engine=_CurationFakeEngine(),
            tags=[],
            heat=0.5,
        )
        return action, mid, store

    def test_contradiction_supersedes_instead_of_merging(self):
        # New content carries a negation the existing one lacks → contradiction.
        action, mid, store = self._run(
            new_content="we no longer use postgres for the memory store",
            existing_content="we use postgres for the memory store",
        )
        assert action == "supersede"
        assert mid == 42
        assert store.merged is False, "supersede must NOT destroy the old row"

    def test_near_duplicate_without_contradiction_still_merges(self):
        action, mid, store = self._run(
            new_content="we use postgres for the memory store backend",
            existing_content="we use postgres for the memory store",
        )
        assert action == "merge"
        assert mid == 42
        assert store.merged is True
