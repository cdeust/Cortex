"""One captured payload is one operation in the background store (issue #733).

The resident worker and the spool drainer run outside any MCP call, so their
samples carried no operation id: the ``remember`` sample of a capture, its
``capture_processed`` and the ``capture_skipped`` of its failure were joined
only by ``op`` and ``ts``.
"""

from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path
from unittest import mock

import pytest

from mcp_server.core import telemetry
from mcp_server.handlers._telemetry_wrap import instrument
from mcp_server.hooks import capture_drain, capture_store
from mcp_server.hooks.capture_dispatch import report_failure
from mcp_server.infrastructure import capture_spool
from mcp_server.infrastructure.capture_server import CaptureServer, ServerPolicy
from mcp_server.infrastructure.capture_transport import Limits
from tests_py.hooks.test_capture_worker_policy import payload


@pytest.fixture
def samples(tmp_path, monkeypatch):
    path = tmp_path / "telemetry.jsonl"
    monkeypatch.setattr(telemetry, "_LOG_PATH", path)
    monkeypatch.delenv("CORTEX_TELEMETRY_DISABLED", raising=False)
    telemetry.set_exporter(None)
    telemetry.reset()
    yield lambda: [json.loads(line) for line in path.read_text().splitlines()]
    telemetry.reset()


def _remember(monkeypatch, impl) -> None:
    """The worker loads this handler: the real telemetry wrapper around ``impl``."""
    handler = instrument("remember", impl, result_count_key=None)
    monkeypatch.setattr(
        "mcp_server.hooks.post_tool_capture._load_remember", lambda: (None, handler)
    )


def _worker_consumes(*payloads) -> None:
    """The resident server's own loop, fed ``payloads``, until its idle timeout."""
    policy = ServerPolicy(Limits(4096, 1, 0.5), report_failure)
    server = CaptureServer(mock.Mock(), capture_store.remember, policy)
    feeder = threading.Thread(target=lambda: [server.pending.put(p) for p in payloads])
    feeder.start()  # the admission queue is bounded: feed it as the receiver does
    asyncio.run(server._consume())
    feeder.join()


def _ids(recorded) -> list[tuple[str, str | None]]:
    return [(sample["op"], sample["operation_id"]) for sample in recorded]


async def _stored(_payload):
    return {"stored": True, "memory_id": 7}


async def _failing(_payload):
    raise RuntimeError("fixture store failure")


def test_the_worker_gives_each_payload_one_operation(samples, monkeypatch):
    _remember(monkeypatch, _stored)
    _worker_consumes(payload("first"), payload("second"))
    (r1, first), (p1, first_too), (r2, second), (p2, second_too) = _ids(samples())
    assert [r1, p1, r2, p2] == ["remember", "capture_processed"] * 2
    assert first is not None and second is not None
    assert first == first_too and second == second_too
    assert first != second


def test_a_failed_store_and_its_skip_report_are_one_operation(samples, monkeypatch):
    _remember(monkeypatch, _failing)
    _worker_consumes(payload())
    (failed, skipped) = samples()
    assert (failed["op"], failed["ok"]) == ("remember", False)
    assert (skipped["op"], skipped["skipped"]) == ("capture_skipped", True)
    assert failed["operation_id"] is not None
    assert skipped["operation_id"] == failed["operation_id"]


def test_a_refused_payload_is_its_own_operation(samples, monkeypatch):
    _remember(monkeypatch, _stored)
    _worker_consumes({}, payload())
    (skip, refused), (_, stored), (_, processed) = _ids(samples())
    assert skip == "capture_skipped"
    assert refused is not None and stored is not None
    assert refused != stored and stored == processed


def test_the_drainer_gives_each_spooled_file_one_operation(
    samples, monkeypatch, tmp_path
):
    _remember(monkeypatch, _stored)
    spool = capture_spool.spool_directory(Path(tmp_path))
    capture_spool.write(spool, payload("first"))
    capture_spool.write(spool, payload("second"))
    capture_drain.drain(spool)
    (r1, first), (p1, first_too), (r2, second), (p2, second_too) = _ids(samples())
    assert [r1, p1, r2, p2] == ["remember", "capture_processed"] * 2
    assert first is not None and second is not None
    assert first == first_too and second == second_too
    assert first != second
    assert capture_spool.pending(spool) == []


def test_a_file_the_drainer_refuses_is_reported_under_its_operation(
    samples, monkeypatch, tmp_path
):
    _remember(monkeypatch, _failing)
    spool = capture_spool.spool_directory(Path(tmp_path))
    capture_spool.write(spool, payload())
    capture_drain.drain(spool)
    (failed, skipped) = samples()
    assert (failed["op"], skipped["op"]) == ("remember", "capture_skipped")
    assert failed["operation_id"] is not None
    assert skipped["operation_id"] == failed["operation_id"]


def test_the_drainer_through_the_real_handler_links_the_stored_memory(
    samples, tmp_path
):
    spool = capture_spool.spool_directory(Path(tmp_path))
    capture_spool.write(spool, payload("the operation of a real capture"))
    capture_drain.drain(spool)
    by_op = dict(_ids(samples()))
    assert by_op["remember"] is not None
    assert by_op["capture_processed"] == by_op["remember"]
    assert capture_spool.pending(spool) == []
