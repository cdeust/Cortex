"""Original-body differential harness; all storage/model behavior is local doubles."""

from __future__ import annotations

import asyncio
from contextlib import ExitStack, contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from mcp_server.core import global_detector, write_gate_calibration
from mcp_server.handlers import remember
from mcp_server.handlers._telemetry_wrap import instrument
from tests_py.handlers._preflight_fakes import Store
from tests_py.handlers.test_remember_batch_handler import handler_patches


FIXTURES = Path(__file__).parents[1] / "fixtures" / "w3_4"


# Names a frozen reference body imported at its own revision that the live
# module no longer imports (#561 moved remember's scope logic into
# global_detector.resolve_global_scope); supplied so the oracle runs unchanged.
_FROZEN_IMPORTS: dict[str, dict] = {
    "remember": {"detect_global": global_detector.detect_global},
}


def original(module, name: str) -> dict:
    namespace = {**vars(module), **_FROZEN_IMPORTS.get(name, {})}
    source = (FIXTURES / f"{name}.py.txt").read_text()
    exec(compile(source, str(FIXTURES / name), "exec"), namespace)
    return namespace


class TraceEngine:
    def __init__(self):
        self.scalars, self.batches = [], []
        self.failures = {}

    def vector(self, text):
        if text in self.failures:
            raise self.failures[text]
        if not text:
            return None
        # Fixture geometry only; exact float32 bytes expose text/position mistakes.
        return np.asarray(
            [len(text), sum(text.encode()), 1], dtype=np.float32
        ).tobytes()

    def encode(self, text):
        self.scalars.append(text)
        return self.vector(text)

    def encode_batch(self, texts):
        self.batches.append(list(texts))
        return [self.vector(text) for text in texts]

    def similarity(self, first, second):
        return 0.0


class TraceStore(Store):
    def __init__(self):
        super().__init__(known=True)
        self.events, self.rows, self.read_versions = [], [], []
        self.fail_insert = None
        self.repeat_after_insert = 0

    def search_vectors(self, embedding, **kwargs):
        return []

    def get_hot_memories(self, **kwargs):
        self.read_versions.append(len(self.rows))
        return [{"content": row[0]} for row in self.rows]

    def insert(self, *args, **kwargs):
        content, embedding, tags, source, domain, directory = args[:6]
        if content == self.fail_insert:
            raise RuntimeError("insert failure")
        self.rows.append((content, embedding, tags, source, domain, directory, kwargs))
        self.repeats = self.repeat_after_insert
        self.events.append(("insert", content, len(self.rows)))
        return {"stored": True, "memory_id": len(self.rows)}

    def update_memory_heat(self, memory_id, heat):
        self.events.append(("heat", memory_id, heat))

    def get_memories_for_entity(self, entity_id):
        return [{"id": len(self.rows) + 1}]


@contextmanager
def harness():
    store, engine = TraceStore(), TraceEngine()
    write_gate_calibration.reset_all_states()
    with ExitStack() as stack:
        stack.callback(write_gate_calibration.reset_all_states)
        for module, name, value in handler_patches(store, engine, "create"):
            if isinstance(value, SimpleNamespace):
                value.DB_PATH = "/fixture-state/memory.db"
                value.SQLITE_FALLBACK_PATH = "/fixture-state/memory.db"
            stack.enter_context(patch.object(module, name, return_value=value))
        stack.enter_context(
            patch.object(remember, "insert_and_post_process", store.insert)
        )
        stack.enter_context(
            patch.object(remember, "try_curation", return_value=("create", None))
        )
        stack.enter_context(
            patch.object(
                remember.wiki_memory_sync, "sync_memory_strict", return_value=None
            )
        )
        telemetry = stack.enter_context(patch("mcp_server.core.telemetry.record"))
        reference = original(remember, "remember")["_handler_impl"]
        yield SimpleNamespace(
            store=store,
            engine=engine,
            reference=reference,
            telemetry=telemetry,
            stack=stack,
        )


def reference_caller(module, fixture: str, function: str, handler):
    namespace = original(module, fixture)
    namespace["remember_handler"] = instrument(
        "remember", handler, result_count_key=None
    )
    return namespace[function]


def run(awaitable):
    return asyncio.run(awaitable)
