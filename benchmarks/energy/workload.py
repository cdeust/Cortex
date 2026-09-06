"""Neural inference, float32 equivalence, and actual model-token accounting."""

from __future__ import annotations

import argparse
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, cast

import numpy as np
from numpy.typing import NDArray

if TYPE_CHECKING:
    from mcp_server.infrastructure.embedding_engine import EmbeddingEngine


class Encoder(Protocol):
    def encode(self, text: str) -> bytes | None: ...

    def encode_batch(self, texts: list[str]) -> list[bytes | None]: ...


class TokenizingModel(Protocol):
    def tokenize(self, texts: list[str]) -> dict[str, object]: ...


class SummableMask(Protocol):
    def sum(self) -> SummableMask: ...

    def item(self) -> int: ...


@dataclass
class Phase:
    condition: str
    repetition: int
    wall_start: float
    wall_end: float
    elapsed_s: float
    operations: int
    tokens: int = 0


def texts(round_id: int, count: int) -> list[str]:
    return [
        f"Cortex energy benchmark unique memory {round_id}:{i}; "
        "batch-equivalence probe."
        for i in range(count)
    ]


def _float32_row(blob: bytes | None) -> NDArray[np.float32]:
    if not blob:
        raise ValueError("missing or empty embedding output")
    # source: numpy.frombuffer docs; engine.encode serializes native float32.
    row = np.frombuffer(blob, dtype=np.float32)
    if not np.isfinite(row).all():
        raise ValueError("non-finite embedding output")
    return row


def verify_equivalence(engine: Encoder, batch_size: int) -> float:
    probes = texts(0, batch_size)
    scalar = [engine.encode(text) for text in probes]
    batched = engine.encode_batch(probes)
    if len(batched) != len(scalar):
        raise ValueError("scalar/batch output count mismatch")
    # source: numpy.finfo documents eps as spacing above 1. No model-wide claim:
    # this strict absolute error budget is checked for this run's probe only.
    tolerance = float(np.finfo(np.float32).eps)
    max_delta = 0.0
    for scalar_blob, batch_blob in zip(scalar, batched, strict=True):
        left, right = _float32_row(scalar_blob), _float32_row(batch_blob)
        if left.shape != right.shape:
            raise ValueError("scalar/batch embedding shape mismatch")
        delta = float(np.max(np.abs(left.astype(np.float64) - right)))
        max_delta = max(max_delta, delta)
        # source: numpy.allclose; explicit atol and zero rtol avoid its defaults.
        if not np.allclose(left, right, rtol=0, atol=tolerance, equal_nan=False):
            raise ValueError(
                f"scalar/batch float32 mismatch: max_abs_delta={delta}, "
                f"atol={tolerance}"
            )
    return max_delta


def count_tokens(model: TokenizingModel, values: list[str]) -> int:
    # source: SentenceTransformer.tokenize returns attention_mask; its sum counts
    # non-padding tokens after the model's truncation, including special tokens.
    mask = cast(SummableMask, model.tokenize(values)["attention_mask"])
    count = int(mask.sum().item())
    if count <= 0:
        raise ValueError("tokenizer returned no active tokens")
    return count


def load_engine() -> EmbeddingEngine:
    # Optional model dependency is loaded only after required CLI arguments pass.
    from mcp_server.infrastructure.embedding_engine import (  # noqa: PLC0415
        EmbeddingEngine,
    )

    engine = EmbeddingEngine()
    engine.encode("Cortex energy benchmark model warm-up")
    if engine.mode != "neural":
        raise RuntimeError(
            "energy benchmark requires the neural model; fallback refused"
        )
    return engine


def _timed_workload(engine: Encoder, mode: str, args: argparse.Namespace) -> int:
    if mode == "idle":
        time.sleep(args.duration_seconds)
        return 0
    deadline = time.perf_counter() + args.duration_seconds
    round_id = 0
    while time.perf_counter() < deadline:
        values = texts(round_id, args.batch_size)
        if mode == "scalar":
            for value in values:
                engine.encode(value)
        else:
            engine.encode_batch(values)
        round_id += 1
    return round_id * args.batch_size


def _measure_phase(
    engine: EmbeddingEngine, mode: str, args: argparse.Namespace, repetition: int
) -> Phase:
    # The probe and earlier phases must not turn scalar inference into LRU hits.
    engine._cache.clear()
    wall_start, perf_start = time.time(), time.perf_counter()
    operations = _timed_workload(engine, mode, args)
    elapsed = time.perf_counter() - perf_start
    phase = Phase(mode, repetition, wall_start, time.time(), elapsed, operations)
    if engine.mode != "neural":
        raise RuntimeError("neural model unavailable after phase; fallback refused")
    if mode != "idle" and operations == 0:
        raise RuntimeError("phase completed no embedding work")
    return phase


def run_phases(engine: EmbeddingEngine, args: argparse.Namespace) -> list[Phase]:
    phases = []
    for repetition in range(args.repetitions):
        # source: original protocol: alternate the two inference conditions.
        modes = ("scalar", "batch")
        order = modes if repetition % len(modes) == 0 else tuple(reversed(modes))
        for condition in ("idle", *order):
            phases.append(_measure_phase(engine, condition, args, repetition))
    model = cast(TokenizingModel, engine._model)
    # Tokenize after ALL timed phases: counting does not inflate measured energy.
    for phase in phases:
        phase.tokens = sum(
            count_tokens(model, texts(round_id, args.batch_size))
            for round_id in range(phase.operations // args.batch_size)
        )
    return phases


def wait_for_stream(args: argparse.Namespace) -> None:
    # One phase duration is the caller's readiness budget; no invented timeout.
    deadline = time.monotonic() + args.duration_seconds
    # source: SI milli prefix: 1000 ms/s (NIST SP 811, chapter 4).
    interval = args.sample_rate_ms / 1000
    while time.monotonic() < deadline:
        if "*** Sampled system activity" in args.external_power_file.read_text():
            return
        time.sleep(min(interval, max(0.0, deadline - time.monotonic())))
    raise RuntimeError("external powermetrics stream did not become ready")
