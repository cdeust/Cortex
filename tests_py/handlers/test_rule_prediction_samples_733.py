"""Rule and prediction tools record one telemetry sample per call (issue #733).

Before, ``add_rule``, ``get_rules``, ``predict``, ``resolve_prediction`` and
``calibration`` were registered without ``instrument``: their wall time, bytes
and outcome were absent from ``get_telemetry`` and the JSONL
(docs/audits/operation-consumption-inventory-2026-11-05.md). These tests drive
each registered ``handler`` and read the JSONL sink.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from pydantic_core import to_json

from mcp_server.core import telemetry
from mcp_server.handlers import (
    add_rule,
    calibration,
    get_rules,
    predict,
    resolve_prediction,
)


@pytest.fixture
def telemetry_log(tmp_path, monkeypatch):
    path = tmp_path / "telemetry.jsonl"
    monkeypatch.setattr(telemetry, "_LOG_PATH", path)
    monkeypatch.delenv("CORTEX_TELEMETRY_DISABLED", raising=False)
    telemetry.reset()
    yield path
    telemetry.reset()


def _samples(path, op: str) -> list[dict]:
    lines = path.read_text().splitlines() if path.exists() else []
    return [s for s in map(json.loads, lines) if s["op"] == op]


# Calls the handler refuses before it opens the store.
_REFUSED = [
    ("add_rule", add_rule, {}),
    ("add_rule", add_rule, {"condition": "x"}),
    ("predict", predict, {"claim": "c"}),
    ("resolve_prediction", resolve_prediction, {}),
]


@pytest.mark.parametrize(("op", "module", "args"), _REFUSED)
def test_a_refused_call_records_one_sample_with_its_bytes(
    telemetry_log, op, module, args
):
    response = asyncio.run(module.handler(args))

    [sample] = _samples(telemetry_log, op)
    assert (sample["ok"], sample["skipped"]) == (True, False)
    assert sample["bytes_in"] == (len(json.dumps(args).encode("utf-8")) if args else 0)
    assert sample["bytes_out"] == len(to_json(response, fallback=str, indent=2))
    assert telemetry.snapshot()[op]["count"] == 1


def test_get_rules_counts_the_rules_it_returns(telemetry_log, monkeypatch):
    rules = [{"scope": "global", "rule_type": "soft"}] * 3
    store = SimpleNamespace(get_all_active_rules=lambda: list(rules))
    monkeypatch.setattr(get_rules, "_get_store", lambda: store)

    response = asyncio.run(get_rules.handler({}))

    [sample] = _samples(telemetry_log, "get_rules")
    assert response["total"] == 3
    assert (sample["ok"], sample["result_count"]) == (True, 3)


def test_calibration_records_one_sample(telemetry_log, monkeypatch):
    monkeypatch.setattr(calibration, "_get_store", lambda: SimpleNamespace(_conn=None))
    monkeypatch.setattr(calibration, "list_predictions", lambda *_a, **_k: [])

    response = asyncio.run(calibration.handler({}))

    [sample] = _samples(telemetry_log, "calibration")
    assert response["open"] == 0
    assert sample["ok"] is True
    assert sample["bytes_out"] == len(to_json(response, fallback=str, indent=2))


def test_a_raising_call_records_an_error_and_reraises(telemetry_log, monkeypatch):
    def broken(*_args, **_kwargs):
        raise RuntimeError("fixture: store unreachable")

    monkeypatch.setattr(predict, "_get_store", broken)
    args = {"claim": "c", "prediction": "p", "test": "t", "confidence": 0.5}
    with pytest.raises(RuntimeError, match="store unreachable"):
        asyncio.run(predict.handler(args))

    [sample] = _samples(telemetry_log, "predict")
    assert (sample["ok"], sample["skipped"], sample["bytes_out"]) == (False, False, 0)


def test_a_call_inside_an_mcp_request_carries_its_operation_id(telemetry_log):
    async def call() -> list[telemetry.TelemetrySample]:
        with telemetry.capture_records() as samples:
            await add_rule.handler({})
        return samples

    captured = asyncio.run(call())
    [sample] = [s for s in captured if s["op"] == "add_rule"]
    assert sample["operation_id"]
    assert _samples(telemetry_log, "add_rule") == []
