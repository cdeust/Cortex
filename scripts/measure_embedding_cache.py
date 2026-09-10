#!/usr/bin/env python3
"""Replay an explicitly supplied session fixture to measure the embedding LRU.

JSONL records: {"method": "encode", "text": "..."} or
{"method": "encode_batch", "texts": ["...", "..."]}. Order is significant.
The report contains no text or cache keys. It records a fixture hash, output
vector digest, cache counters, CPU and wall time. Model initialization and an
optional whole-session primer are reported separately from each timed replay.

Run later, sequentially, in an isolated environment with the existing model
cache and CORTEX_EMBEDDING_ZERO_DOWNLOAD=1. Compare --capacity 0 to the retained
default, with and without --warm-session. No capacity is recommended here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sys
import time
from pathlib import Path
from typing import Any


def _operation(record: Any, line_number: int) -> tuple[str, str | list[str]]:
    method = record.get("method") if isinstance(record, dict) else None
    if method == "encode" and isinstance(record.get("text"), str):
        return method, record["text"]
    if method == "encode_batch" and isinstance(record.get("texts"), list):
        if all(isinstance(text, str) for text in record["texts"]):
            return method, record["texts"]
    raise ValueError(f"Invalid operation at fixture line {line_number}")


def operations(path: Path):
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            yield _operation(json.loads(line), line_number)


def replay(engine: Any, fixture: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    count = 0
    for method, argument in operations(fixture):
        vectors = (
            [engine.encode(argument)]
            if method == "encode"
            else engine.encode_batch(argument)
        )
        for vector in vectors:
            if vector is not None and not isinstance(vector, bytes):
                raise TypeError("Encoder output must be bytes or None")
            marker = {"length": len(vector) if vector is not None else None}
            digest.update(json.dumps(marker, sort_keys=True).encode())
            if vector is not None:
                digest.update(vector)
            count += 1
    return {"vectors": count, "vectors_sha256": digest.hexdigest()}


def snapshot() -> dict[str, float]:
    # source: ADR-0761
    usage = os.times()
    return {
        "user_seconds": usage.user,
        "system_seconds": usage.system,
        # source: ADR-0761
        "cpu_seconds": time.process_time(),
        "wall_seconds": time.perf_counter(),
    }


def timed_replay(engine: Any, fixture: Path) -> dict[str, Any]:
    before, cache_before = snapshot(), engine.cache_info()
    result = replay(engine, fixture)
    if engine.mode != "neural":
        raise RuntimeError("Encoder changed to fallback during the measured session")
    after, cache_after = snapshot(), engine.cache_info()
    result.update({key: after[key] - before[key] for key in before})
    result["cache"] = {
        key: cache_after[key] - cache_before[key]
        for key in ("hits", "misses", "batch_reuses")
    }
    result["cache"].update({key: cache_after[key] for key in ("size", "capacity")})
    lookups = result["cache"]["hits"] + result["cache"]["misses"]
    result["cache"]["hit_rate"] = result["cache"]["hits"] / lookups if lookups else None
    return result


def samples(engine: Any, fixture: Path, repetitions: int, warm: bool) -> list[dict]:
    result = []
    for repetition in range(repetitions):
        engine._cache.clear()
        primer = timed_replay(engine, fixture) if warm else None
        measured = timed_replay(engine, fixture)
        measured.update(
            {"repetition": repetition, "discarded": repetition == 0, "primer": primer}
        )
        result.append(measured)
    return result


def load_engine(capacity: int | None):
    if os.environ.get("CORTEX_EMBEDDING_ZERO_DOWNLOAD", "").lower() not in (
        "1",
        "true",
    ):
        raise RuntimeError(
            "Set CORTEX_EMBEDDING_ZERO_DOWNLOAD=1; downloads are forbidden"
        )
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from mcp_server.infrastructure.embedding_engine import EmbeddingEngine  # noqa: PLC0415 — model load only at explicit measurement entry, never during script import

    engine = EmbeddingEngine()
    if capacity is not None:
        if capacity < 0:
            raise ValueError("Capacity must be nonnegative")
        engine._cache_max = capacity
    if engine.mode != "neural":
        raise RuntimeError("Neural cache unavailable; do not compare fallback results")
    return engine


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for line in stream:
            digest.update(line)
    return digest.hexdigest()


def source_hashes() -> dict[str, str]:
    root = Path(__file__).resolve().parents[1]
    paths = (
        "mcp_server/infrastructure/embedding_engine.py",
        "mcp_server/infrastructure/embedding_cache.py",
        "uv.lock",
    )
    return {path: file_hash(root / path) for path in paths}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--capacity", type=int)
    parser.add_argument("--warm-session", action="store_true")
    # source: ADR-0761
    parser.add_argument("--repetitions", type=int, default=4)
    args = parser.parse_args()
    if args.repetitions <= 1:
        parser.error(
            "Need a discarded first repetition and at least one retained sample"
        )
    for _operation in operations(args.fixture):
        pass  # Validate every record before loading a model.
    setup_before = snapshot()
    engine = load_engine(args.capacity)
    setup_after = snapshot()
    report = {
        "python": sys.version,
        "platform": platform.platform(),
        "fixture_sha256": file_hash(args.fixture),
        "source_sha256": source_hashes(),
        "model": engine.model_name,
        "revision": engine.revision,
        "mode": engine.mode,
        "capacity": engine.cache_info()["capacity"],
        "warm_session": args.warm_session,
        "model_setup": {
            key: setup_after[key] - setup_before[key] for key in setup_before
        },
        "samples": samples(engine, args.fixture, args.repetitions, args.warm_session),
        "timing_scope": (
            "fixture read, encode, digest and counters; setup and primer separate; "
            "CPU total from process_time, user/system from os.times"
        ),
    }
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
