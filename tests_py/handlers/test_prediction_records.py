"""Prediction records, from writing one to scoring the confidences (#597).

Cortex stored what happened and never what was expected, so it could not be
wrong in a way it noticed. These tests drive the three tools on SQLite, the
default backend, through the handlers' own composition root.

source: ADR-1076
"""

from __future__ import annotations

import asyncio

import pytest
from mcp.server.mcpserver import MCPServer

from mcp_server import tool_registry_predictions as registry

OPEN = {
    "claim": "the timeout comes from connection-pool exhaustion",
    "prediction": "raising concurrency raises the failure rate",
    "test": "run the load test at twice the concurrency",
    "confidence": 0.8,
}
REVIEW_REF = "https://github.com/owner/repo/pull/12#issuecomment-345"


@pytest.fixture()
def sqlite_store(tmp_path, monkeypatch):
    from mcp_server.infrastructure.memory_config import get_memory_settings
    from mcp_server.infrastructure.memory_store import (
        get_shared_store,
        reset_shared_store,
    )

    db = tmp_path / "memory.db"
    monkeypatch.setenv("CORTEX_MEMORY_STORE_BACKEND", "sqlite")
    monkeypatch.setenv("CORTEX_MEMORY_DB_PATH", str(db))
    monkeypatch.setenv("CORTEX_MEMORY_SQLITE_FALLBACK_PATH", str(db))
    get_memory_settings.cache_clear()
    reset_shared_store()

    settings = get_memory_settings()
    store = get_shared_store(settings.DB_PATH, settings.EMBEDDING_DIM)
    yield store

    reset_shared_store()
    get_memory_settings.cache_clear()


async def _write(**overrides) -> int:
    from mcp_server.handlers.predict import handler as predict

    out = await predict({**OPEN, **overrides})
    assert "error" not in out, out
    return out["prediction_id"]


@pytest.mark.asyncio
async def test_a_prediction_is_written_open(sqlite_store) -> None:
    from mcp_server.handlers.predict import handler as predict

    out = await predict(OPEN)

    assert out["status"] == "open"
    assert out["prediction_id"] > 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("payload", "named"),
    [
        ({"claim": "   "}, "claim"),
        ({"prediction": ""}, "prediction"),
        ({"test": "  "}, "test"),
    ],
    ids=["blank-claim", "empty-prediction", "blank-test"],
)
async def test_a_prediction_without_its_parts_is_refused(
    sqlite_store, payload, named
) -> None:
    from mcp_server.handlers.predict import handler as predict

    out = await predict({**OPEN, **payload})

    assert named in out["error"]


@pytest.mark.asyncio
@pytest.mark.parametrize("confidence", [None, -0.1, 1.4], ids=["none", "low", "high"])
async def test_a_confidence_outside_zero_to_one_is_refused(
    sqlite_store, confidence
) -> None:
    from mcp_server.handlers.predict import handler as predict

    out = await predict({**OPEN, "confidence": confidence})

    assert "confidence" in out["error"]


@pytest.mark.asyncio
async def test_a_resolution_names_its_evidence(sqlite_store) -> None:
    """The contract that makes this work in any repository."""
    from mcp_server.handlers.resolve_prediction import handler as resolve

    prediction_id = await _write()

    out = await resolve(
        {
            "prediction_id": prediction_id,
            "verdict": "confirmed",
            "observed": "the failure rate doubled",
            "source_kind": "review",
            "source_ref": "   ",
        }
    )

    assert out["resolved"] is False
    assert "source_ref" in out["error"]


@pytest.mark.asyncio
async def test_a_prediction_resolves_once(sqlite_store) -> None:
    from mcp_server.handlers.resolve_prediction import handler as resolve

    prediction_id = await _write()
    settled = {
        "prediction_id": prediction_id,
        "verdict": "confirmed",
        "observed": "the failure rate doubled",
        "source_kind": "review",
        "source_ref": REVIEW_REF,
    }

    first = await resolve(settled)
    second = await resolve({**settled, "verdict": "refuted"})

    assert first["resolved"] is True
    assert second["resolved"] is False
    assert "already resolved" in second["error"]


@pytest.mark.asyncio
async def test_an_unknown_prediction_is_not_resolved(sqlite_store) -> None:
    from mcp_server.handlers.resolve_prediction import handler as resolve

    out = await resolve(
        {
            "prediction_id": 4321,
            "verdict": "confirmed",
            "observed": "x",
            "source_kind": "ci",
            "source_ref": "run/1",
        }
    )

    assert out["resolved"] is False
    assert "not found" in out["error"]


@pytest.mark.asyncio
async def test_calibration_scores_the_resolved_and_counts_the_open(
    sqlite_store,
) -> None:
    from mcp_server.handlers.calibration import handler as calibration
    from mcp_server.handlers.resolve_prediction import handler as resolve

    confident = await _write(confidence=0.8)
    hesitant = await _write(confidence=0.6, claim="warm cache halves latency")
    await _write(confidence=0.5, claim="still open")
    await resolve(
        {
            "prediction_id": confident,
            "verdict": "confirmed",
            "observed": "the failure rate doubled",
            "source_kind": "review",
            "source_ref": REVIEW_REF,
        }
    )
    await resolve(
        {
            "prediction_id": hesitant,
            "verdict": "refuted",
            "observed": "latency unchanged",
            "source_kind": "ci",
            "source_ref": "run/99",
        }
    )

    report = await calibration({})

    assert report["scored"] == 2
    assert report["confirmed"] == 1
    assert report["refuted"] == 1
    assert report["open"] == 1
    assert report["brier"] == pytest.approx(((0.8 - 1) ** 2 + (0.6 - 0) ** 2) / 2)
    assert report["uninformative_brier"] == 0.25


@pytest.mark.asyncio
async def test_calibration_says_so_when_nothing_is_resolved(sqlite_store) -> None:
    from mcp_server.handlers.calibration import handler as calibration

    await _write()

    report = await calibration({})

    assert report["scored"] == 0
    assert report["brier"] is None
    assert "no resolved prediction" in report["note"]


def test_the_three_tools_are_registered() -> None:
    mcp = MCPServer(name="prediction-tools-test")
    registry.register(mcp)

    tools = {t.name: t for t in asyncio.run(mcp.list_tools())}

    assert set(tools) == {"predict", "resolve_prediction", "calibration"}
    assert tools["calibration"].annotations.read_only_hint is True
    assert tools["predict"].annotations.read_only_hint is False
