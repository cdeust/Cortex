"""End-to-end contract for the REAL all-MiniLM-L6-v2 embedding model.

Why this file exists
--------------------
Every other embedding test mocks ``sentence_transformers.SentenceTransformer``.
A mock proves the wiring; it cannot prove the model still loads and computes
after a dependency bump. That gap is not theoretical here:

  * ``_EmbeddingLifecycleMixin._finalize_loaded`` SILENTLY reconciles a
    dimension mismatch (``if actual_dim != self._dim: self._dim = actual_dim``).
    A model that started returning a different width would be accepted without
    a word, and every stored vector would change space.
  * Every non-LOADED ``ModelState`` degrades to the algorithmic fallback, which
    also returns 384-dim L2-normalised vectors. Shape alone therefore does NOT
    distinguish "the neural model ran" from "the model failed to load and the
    hash fallback answered" — the exact silent degradation the 2026-07-11
    FlashRank incident cost six benchmarks.

So this file asserts the two things a mock cannot: the model reaches
``ModelState.LOADED`` (provenance), and the vectors it emits carry real
semantic structure (behaviour), not just the right shape.

Added with the transformers 4.57.6 -> 5.x migration: `import` succeeding is not
evidence that the embedding stack survived a major bump.

Skip discipline
---------------
The weights must be on disk. Every CI job that runs pytest has a
"Pre-download embedding model" step that fetches them and fails the job loudly
when it cannot (.github/workflows/ci.yml — test, test-sqlite, test-windows), so
in CI an unloadable model is a real defect and this file FAILS. On a
contributor's machine the weights may legitimately be absent, so it skips.
A silent skip in CI would make this file worthless, which is why the two cases
are distinguished rather than both skipped.
"""

from __future__ import annotations

import math
import os
import struct

import pytest

from mcp_server.infrastructure.embedding_engine import EmbeddingEngine
from mcp_server.infrastructure.embedding_model_lifecycle import (
    DEFAULT_MODEL_REVISION,
    ModelState,
)

# GitHub Actions sets CI=true; matches tests_py/conftest.py's convention.
_IS_CI = os.environ.get("CI", "").lower() in ("true", "1")

# source: model card, https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2
# ("maps sentences & paragraphs to a 384 dimensional dense vector space").
EXPECTED_MODEL_NAME = "all-MiniLM-L6-v2"
EXPECTED_DIM = 384
_FLOAT32_BYTES = 4


@pytest.fixture(scope="module")
def live_engine() -> EmbeddingEngine:
    """The production engine with the real weights loaded, or skip/fail.

    Module-scoped: loading all-MiniLM-L6-v2 costs seconds, and every test here
    reads the same immutable model.
    """
    engine = EmbeddingEngine()
    # `mode` forces resolution through the production load path (_ensure_model)
    # rather than reaching into a private method.
    mode = engine.mode
    if engine.model_state is ModelState.LOADED:
        return engine

    reason = (
        f"real {EXPECTED_MODEL_NAME} weights unavailable: "
        f"model_state={engine.model_state.name}, mode={mode}"
    )
    if _IS_CI:
        pytest.fail(
            reason + " — CI pre-downloads this model and fails loudly when it "
            "cannot, so reaching the fallback here is a genuine defect, not a "
            "missing fixture."
        )
    pytest.skip(reason)


def _to_floats(blob: bytes) -> list[float]:
    """Decode the engine's float32 blob without going through the engine."""
    return list(struct.unpack(f"<{len(blob) // _FLOAT32_BYTES}f", blob))


def test_live_model_reports_neural_provenance(live_engine: EmbeddingEngine) -> None:
    """The neural model is what answered — not the algorithmic fallback.

    This is the assertion that separates "transformers 5 works" from
    "transformers 5 broke the load and nobody noticed".
    """
    assert live_engine.model_state is ModelState.LOADED
    assert live_engine.mode == "neural"
    assert live_engine.model_name == EXPECTED_MODEL_NAME
    assert live_engine.revision == DEFAULT_MODEL_REVISION


def test_live_model_dimension_is_384(live_engine: EmbeddingEngine) -> None:
    """The model's OWN reported width is 384.

    Asserted on the reconciled value, because _finalize_loaded overwrites the
    requested dimension with the model's actual one without raising.
    """
    assert live_engine.dimensions == EXPECTED_DIM


def test_live_encode_emits_a_384_float32_vector(live_engine: EmbeddingEngine) -> None:
    """encode() returns exactly 384 finite float32 values, L2-normalised."""
    blob = live_engine.encode("Cortex stores memories as dense vectors.")

    assert blob is not None
    assert len(blob) == EXPECTED_DIM * _FLOAT32_BYTES

    values = _to_floats(blob)
    assert len(values) == EXPECTED_DIM
    assert all(math.isfinite(v) for v in values)
    # The engine L2-normalises every vector (_EmbeddingMathMixin._normalize),
    # so cosine similarity is a plain dot product downstream.
    assert math.sqrt(sum(v * v for v in values)) == pytest.approx(1.0, abs=1e-5)
    # A collapsed/zero model would still satisfy the norm check only by
    # accident; require genuine spread.
    assert len(set(values)) > 1


def test_live_encode_is_deterministic(live_engine: EmbeddingEngine) -> None:
    """The same text encodes to the same bytes across calls.

    Uses two distinct engine instances so the assertion cannot be satisfied by
    the LRU cache alone (a cache hit would make any model look deterministic).
    """
    text = "Determinism is a property of the model, not of the cache."
    first = live_engine.encode(text)

    second_engine = EmbeddingEngine()
    second = second_engine.encode(text)

    assert second_engine.model_state is ModelState.LOADED
    assert first == second


def test_live_embeddings_carry_semantic_structure(
    live_engine: EmbeddingEngine,
) -> None:
    """Paraphrases sit closer than unrelated text — the weights really ran.

    This is the end-to-end behavioural check. Shape and provenance can both be
    right while the forward pass returns garbage; ordering cannot. Asserted as
    a strict ordering rather than against a similarity threshold, so there is
    no unsourced numeric constant to drift.
    """
    anchor = live_engine.encode("The cat is sleeping on the sofa.")
    paraphrase = live_engine.encode("A cat naps on the couch.")
    unrelated = live_engine.encode("Quarterly revenue exceeded analyst estimates.")

    assert anchor is not None
    assert paraphrase is not None
    assert unrelated is not None

    near = live_engine.similarity(anchor, paraphrase)
    far = live_engine.similarity(anchor, unrelated)

    assert live_engine.similarity(anchor, anchor) == pytest.approx(1.0, abs=1e-5)
    assert near > far


def test_live_encode_batch_matches_single_encode(
    live_engine: EmbeddingEngine,
) -> None:
    """The batch path produces the same vectors as the single-text path.

    Both are used in production (ingest batches, recall encodes one query), and
    a divergence between them would put stored and query vectors in different
    spaces without any error surfacing.
    """
    texts = ["first memory to embed", "second memory to embed"]

    batch = live_engine.encode_batch(texts)

    assert [live_engine.encode(t) for t in texts] == batch
    assert all(b is not None and len(b) == EXPECTED_DIM * _FLOAT32_BYTES for b in batch)
