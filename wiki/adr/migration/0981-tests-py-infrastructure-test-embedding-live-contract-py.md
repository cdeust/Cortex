# ADR-0981: tests_py/infrastructure/test_embedding_live_contract.py design and historical evidence

Status: accepted; existing test/harness evidence preserved during issue #514.

Source `tests_py/infrastructure/test_embedding_live_contract.py`, original SHA-256 `0b8723722ff54e3669b49bb6d1f4369fda3bbd3e91ba17a900ee4a8d6c334410`.
Assertions and runtime fixture literals remain unchanged.

## Original docstring, lines 1–35

````text
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
````

## Original docstring, lines 176–196

````text
"""Batch and single encoding put a text in the SAME place in the space.

    Both paths run in production — ingest encodes in batches, recall encodes
    one query — so a divergence between them would compare stored vectors
    against query vectors from a different space, with nothing raising.

    Agreement is asserted as an ordering, not as equality: each batch vector
    must be closer to its OWN single-encoded counterpart than to any other
    text's. Byte equality is not a property the model offers — a batched
    forward pass reduces its matrix products in a different order from a
    single one, so the two agree only to float32 rounding. Measured on CI run
    30471706750 (Python 3.12, Linux, transformers 5.14.1): the two paths
    produced vectors differing in the low-order bits of the float32 mantissa
    (`\\xf9\\xbc...` vs `\\xff\\xbc...`) for the same text. An equality
    assertion there tests the GEMM kernel, not Cortex.

    The ordering form still fails on everything that actually matters —
    wrong-order results, a different pooling, a truncated batch, or vectors
    landing in a different space — and carries no tolerance constant that
    could drift.
    """
````

