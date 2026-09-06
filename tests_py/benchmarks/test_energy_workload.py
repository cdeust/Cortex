"""Energy harness contracts with deterministic float32/token-mask fixtures.

All numbers here describe synthetic fixtures; none is a host energy measurement.
"""

from argparse import Namespace
from types import SimpleNamespace
import sys

import numpy as np
import pytest

from benchmarks.energy import workload


class FixtureEncoder:
    def __init__(self, scalar, batch):
        self.scalar = scalar
        self.batch = batch

    def encode(self, text):
        return self.scalar

    def encode_batch(self, values):
        return [self.batch] * len(values)


def test_float32_equivalence_accepts_different_bytes():
    scalar = np.array([0.5], dtype=np.float32)
    batch = np.nextafter(scalar, np.float32(1))
    assert scalar.tobytes() != batch.tobytes()
    # Before W0-2 the same fixture returned the byte difference 1.0.
    assert (
        max(abs(a - b) for a, b in zip(scalar.tobytes(), batch.tobytes(), strict=True))
        == 1
    )
    delta = workload.verify_equivalence(
        FixtureEncoder(scalar.tobytes(), batch.tobytes()), 4
    )
    assert delta == float(batch[0]) - float(scalar[0])
    assert 0 < delta <= np.finfo(np.float32).eps


def test_float32_equivalence_rejects_real_difference():
    engine = FixtureEncoder(
        np.array([0.5], dtype=np.float32).tobytes(),
        np.array([0.75], dtype=np.float32).tobytes(),
    )
    with pytest.raises(ValueError, match="float32 mismatch"):
        workload.verify_equivalence(engine, 4)


@pytest.mark.parametrize(
    ("batch", "message"),
    [
        (None, "missing"),
        (b"", "empty"),
        (b"abc", "multiple"),
        (np.array([float("nan")], dtype=np.float32).tobytes(), "non-finite"),
        (np.array([float("inf")], dtype=np.float32).tobytes(), "non-finite"),
        (np.array([0.5, 0.5], dtype=np.float32).tobytes(), "shape mismatch"),
    ],
)
def test_float32_equivalence_refuses_invalid_outputs(batch, message):
    engine = FixtureEncoder(np.array([0.5], dtype=np.float32).tobytes(), batch)
    with pytest.raises(ValueError, match=message):
        workload.verify_equivalence(engine, 4)


def test_float32_equivalence_refuses_output_count_mismatch(monkeypatch):
    engine = FixtureEncoder(np.array([0.5], dtype=np.float32).tobytes(), None)
    monkeypatch.setattr(engine, "encode_batch", lambda values: [])
    with pytest.raises(ValueError, match="count mismatch"):
        workload.verify_equivalence(engine, 4)


class FixtureTokenizer:
    def __init__(self):
        self.calls = []

    def tokenize(self, values):
        self.calls.append(values)
        # Already truncated model input: three active tokens, two active, padding.
        return {"attention_mask": np.array([[1, 1, 1, 0], [1, 1, 0, 0]])}


def test_token_count_uses_model_attention_mask():
    model = FixtureTokenizer()
    values = ["é", "a much longer input whose character count is irrelevant"]
    assert workload.count_tokens(model, values) == 5
    assert model.calls == [values]


def test_token_count_refuses_empty_mask():
    model = SimpleNamespace(
        tokenize=lambda values: {"attention_mask": np.zeros((1, 1))}
    )
    with pytest.raises(ValueError, match="no active tokens"):
        workload.count_tokens(model, ["input"])


def test_phases_count_exact_completed_batches_outside_measurement(monkeypatch):
    model = FixtureTokenizer()

    def measure(engine, mode, args, repetition):
        assert not model.calls, "token counting must follow all timed phases"
        return workload.Phase(mode, repetition, 0, 1, 1, 0 if mode == "idle" else 4)

    monkeypatch.setattr(workload, "_measure_phase", measure)
    args = Namespace(repetitions=2, batch_size=2)
    phases = workload.run_phases(SimpleNamespace(_model=model), args)
    assert [phase.condition for phase in phases] == [
        "idle",
        "scalar",
        "batch",
        "idle",
        "batch",
        "scalar",
    ]
    assert [phase.tokens for phase in phases] == [0, 10, 10, 0, 10, 10]
    assert model.calls == [workload.texts(i, 2) for _ in range(4) for i in range(2)]


@pytest.mark.parametrize("mode", ["scalar", "batch"])
def test_timed_workload_counts_completed_texts(mode, monkeypatch):
    ticks = iter([0, 0, 2])
    monkeypatch.setattr(workload.time, "perf_counter", lambda: next(ticks))
    calls = []
    engine = SimpleNamespace(encode=calls.append, encode_batch=calls.extend)
    args = Namespace(duration_seconds=1, batch_size=4)
    assert workload._timed_workload(engine, mode, args) == 4
    assert calls == workload.texts(0, 4)


def test_load_engine_refuses_algorithmic_fallback(monkeypatch):
    engine = SimpleNamespace(encode=lambda text: None, mode="fallback")
    module = SimpleNamespace(EmbeddingEngine=lambda: engine)
    monkeypatch.setitem(
        sys.modules, "mcp_server.infrastructure.embedding_engine", module
    )
    with pytest.raises(RuntimeError, match="fallback refused"):
        workload.load_engine()


def test_phase_clears_warm_cache_and_refuses_fallback(monkeypatch):
    engine = SimpleNamespace(_cache={"warm": b"embedding"}, mode="fallback")
    monkeypatch.setattr(workload, "_timed_workload", lambda *args: 1)
    with pytest.raises(RuntimeError, match="fallback refused"):
        workload._measure_phase(engine, "scalar", Namespace(), 0)
    assert engine._cache == {}


def test_phase_refuses_no_completed_work(monkeypatch):
    engine = SimpleNamespace(_cache={}, mode="neural")
    monkeypatch.setattr(workload, "_timed_workload", lambda *args: 0)
    with pytest.raises(RuntimeError, match="no embedding work"):
        workload._measure_phase(engine, "scalar", Namespace(), 0)


def test_stream_timeout_is_explicit(tmp_path, monkeypatch):
    path = tmp_path / "power.txt"
    path.write_text("")
    ticks = iter([0, 0, 0, 2])
    monkeypatch.setattr(workload.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(workload.time, "sleep", lambda duration: None)
    args = Namespace(duration_seconds=1, sample_rate_ms=1, external_power_file=path)
    with pytest.raises(RuntimeError, match="stream did not become ready"):
        workload.wait_for_stream(args)


def test_stream_file_error_is_not_swallowed(tmp_path):
    args = Namespace(
        duration_seconds=1, sample_rate_ms=1, external_power_file=tmp_path / "missing"
    )
    with pytest.raises(FileNotFoundError):
        workload.wait_for_stream(args)
