"""Regression tests for per-stage telemetry in consolidate handler.

Covers the uncommitted telemetry patch (issue #13, darval):
- `_timed` wrapper in mcp_server.handlers.consolidate injects duration_ms
  into each stage result and captures stage exceptions as {"error": ...}
  without propagating, so sibling stages keep running.
- `run_homeostatic_cycle` in mcp_server.handlers.consolidation.homeostatic
  explicitly distinguishes an empty store ({"reason": "no_memories"}) from
  a stage-level exception ({"error": "..."}).

Uses the shared test conftest — autouse fixture already resets handler
singletons and cleans the store between tests.
"""

from __future__ import annotations

import pytest

from mcp_server.handlers import consolidate as consolidate_handler
from mcp_server.handlers.consolidate import _timed
from mcp_server.handlers.consolidation.homeostatic import run_homeostatic_cycle


class TestTimedWrapper:
    """Unit tests for the _timed telemetry wrapper."""

    def test_timed_wrapper_adds_duration_ms(self):
        """_timed injects a non-negative integer duration_ms into dict results."""

        def stage() -> dict:
            return {"memories_decayed": 3, "total_memories": 10}

        result = _timed(stage)

        assert "duration_ms" in result
        assert isinstance(result["duration_ms"], int)
        assert result["duration_ms"] >= 0
        # original keys preserved
        assert result["memories_decayed"] == 3
        assert result["total_memories"] == 10

    def test_timed_wrapper_captures_exception_without_propagating(self):
        """A raised exception is returned as {"error": ..., "duration_ms": ...}."""

        def broken_stage():
            raise RuntimeError("simulated stage failure")

        # must NOT raise
        result = _timed(broken_stage)

        assert "error" in result
        assert "RuntimeError" in result["error"]
        assert "simulated stage failure" in result["error"]
        assert "duration_ms" in result
        assert isinstance(result["duration_ms"], int)
        assert result["duration_ms"] >= 0

    def test_timed_wrapper_handles_none_result(self):
        """A stage returning None is normalized to a dict with duration_ms."""

        def silent_stage():
            return None

        result = _timed(silent_stage)

        assert isinstance(result, dict)
        assert "duration_ms" in result

    def test_timed_wrapper_forwards_args_and_kwargs(self):
        """_timed passes *args and **kwargs through to the wrapped callable."""

        def stage(a, b, *, c):
            return {"sum": a + b + c}

        result = _timed(stage, 1, 2, c=3)

        assert result["sum"] == 6
        assert "duration_ms" in result


class TestConsolidateHandlerTelemetry:
    """Integration tests: full handler wires _timed into every stage."""

    @pytest.mark.asyncio
    async def test_consolidate_returns_duration_per_stage(self):
        """Each stage dict in the consolidate result carries a duration_ms."""
        result = await consolidate_handler.handler()

        # Top-level total duration
        assert "duration_ms" in result

        # Every _timed-wrapped stage that ran (default flags on)
        # NOTE: emergence uses an inline try/except (not _timed), so its
        # duration_ms is only present on success, not on the error path —
        # we therefore don't assert on it here.
        timed_stages = [
            "decay",
            "plasticity",
            "pruning",
            "compression",
            "cls",
            "memify",
            "cascade",
            "homeostatic",
        ]
        for stage in timed_stages:
            assert stage in result, f"missing stage: {stage}"
            assert isinstance(result[stage], dict), f"{stage} not a dict"
            assert "duration_ms" in result[stage], (
                f"{stage} missing duration_ms: {result[stage]!r}"
            )
            assert isinstance(result[stage]["duration_ms"], int)
            assert result[stage]["duration_ms"] >= 0

    @pytest.mark.asyncio
    async def test_consolidate_stage_exception_does_not_crash_siblings(
        self, monkeypatch
    ):
        """If one stage raises, other stages still run and an error field surfaces."""
        from mcp_server.handlers.consolidation import decay as decay_mod

        def exploding_decay(store, settings, memories=None):
            raise RuntimeError("boom in decay")

        monkeypatch.setattr(decay_mod, "run_decay_cycle", exploding_decay)
        # Also patch the re-export imported by consolidate.py at module load time
        monkeypatch.setattr(consolidate_handler, "run_decay_cycle", exploding_decay)

        result = await consolidate_handler.handler()

        # decay failed with an error field, but siblings ran
        assert "decay" in result
        assert "error" in result["decay"]
        assert "RuntimeError" in result["decay"]["error"]
        assert "duration_ms" in result["decay"]

        # siblings produced normal results (not errors)
        assert "compression" in result
        assert "error" not in result["compression"]
        assert "cls" in result
        assert "error" not in result["cls"]
        assert "homeostatic" in result
        assert "duration_ms" in result["homeostatic"]


class TestHomeostaticReporting:
    """Contract tests for empty-store vs exception-path reporting."""

    def test_homeostatic_empty_store_reports_reason(self):
        """On an empty store, reports reason=no_memories (not an error)."""

        class EmptyStore:
            def get_all_memories_for_decay(self):
                return []

        result = run_homeostatic_cycle(EmptyStore())

        assert result["scaling_applied"] is False
        assert result["health_score"] is None
        assert result["reason"] == "no_memories"
        assert result["memories_scanned"] == 0
        # Must NOT be classified as an error
        assert "error" not in result

    def test_homeostatic_exception_surfaces_error_field(self):
        """On store exception, surfaces error field (not reason=no_memories)."""

        class BrokenStore:
            def get_all_memories_for_decay(self):
                raise RuntimeError("db connection lost")

        result = run_homeostatic_cycle(BrokenStore())

        assert result["scaling_applied"] is False
        assert result["health_score"] is None
        assert "error" in result
        assert "RuntimeError" in result["error"]
        assert "db connection lost" in result["error"]
        # Must NOT be confused with the empty-store legitimate case
        assert result.get("reason") != "no_memories"
