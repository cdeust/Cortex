"""Explicit real-model companion to the W3-3 token-only feasibility audit."""

from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path

# source: ADR-0736
REPETITIONS = 4


def load_engine(snapshot: Path):
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["CORTEX_EMBEDDING_ZERO_DOWNLOAD"] = "1"
    from sentence_transformers import SentenceTransformer  # noqa: PLC0415 — opt-in real model measurement, offline and explicit CPU
    from mcp_server.infrastructure.embedding_engine import EmbeddingEngine  # noqa: PLC0415 — measure the actual engine normalization/cache path
    from mcp_server.infrastructure.embedding_model_lifecycle import ModelState  # noqa: PLC0415 — explicit loaded state prevents fallback/download

    model = SentenceTransformer(str(snapshot), device="cpu", local_files_only=True)
    engine = EmbeddingEngine(device="cpu")
    engine._model = model
    engine._model_state = ModelState.LOADED
    engine._device = "cpu"
    return engine


def timed_encode(engine, text: str):
    # Never measure an LRU hit as an encode speedup.
    engine._cache.clear()
    cpu, wall = time.process_time(), time.perf_counter()
    blob = engine.encode(text)
    timing = {
        "cpu_seconds": time.process_time() - cpu,
        "wall_seconds": time.perf_counter() - wall,
    }
    if engine.mode != "neural" or blob is None:
        raise RuntimeError(
            "measurement requires neural bytes; fallback is not evidence"
        )
    return blob, timing


def measure_pair(engine, text: str, cap: int) -> dict:
    samples = []
    equal = []
    for index in range(REPETITIONS):
        before, before_time = timed_encode(engine, text)
        after, after_time = timed_encode(engine, text[:cap])
        equal.append(before == after)
        if index:
            samples.append({"before": before_time, "candidate": after_time})
    return {
        "bytes_equal_every_repetition": all(equal),
        "before_sha256": hashlib.sha256(before).hexdigest(),
        "candidate_sha256": hashlib.sha256(after).hexdigest(),
        "retained_samples": samples,
    }


def input_signature(model, text: str) -> dict:
    # Actual ST preprocessing, including its runtime version's formatting.
    features = model.tokenize([text])
    return {
        key: features[key].tolist()
        for key in ("input_ids", "token_type_ids", "attention_mask")
        if key in features
    }


def measure_model(snapshot: Path, cases: dict[str, str], cap: int) -> dict:
    engine = load_engine(snapshot)
    rows = {}
    for name, text in cases.items():
        rows[name] = measure_pair(engine, text, cap)
        rows[name]["actual_preprocessing_equal"] = input_signature(
            engine._model, text
        ) == input_signature(engine._model, text[:cap])
    return {
        "device": engine._device,
        "model_max_seq_length": engine._model.max_seq_length,
        "mode": engine.mode,
        "cache_cleared_before_every_encode": True,
        "samples": rows,
        "preserves_fixture_bytes": all(
            row["bytes_equal_every_repetition"] for row in rows.values()
        ),
    }
