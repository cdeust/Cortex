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
                    "content": "RuntimeError: connection refused. The server crashed with a traceback.",
                }
            )
        )
        assert result["stored"] is True
        assert result["reason"] == "bypass_error"

    def test_decision_content_bypasses_gate(self):
        result = asyncio.run(
            handler(
                {
                    "content": "We decided to migrate from MySQL to PostgreSQL for the new project.",
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
                    "content": "TODO: fix the parser before release. Remember to update docs.",
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
        from mcp_server.infrastructure.memory_store import MemoryStore

        s = get_memory_settings()
        store = MemoryStore(s.DB_PATH, s.EMBEDDING_DIM)
        mem = store.get_memory(mem_id)
        assert mem is not None
        assert mem.get("is_global") is True or mem.get("is_global") == 1

    def test_response_shape(self):
        result = asyncio.run(
            handler(
                {
                    "content": "Shape test content with error keyword to ensure storage",
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
