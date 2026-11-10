"""Is the FlashRank weights file the one Cortex's published results measured?

Issue #734, slice 3. The reranker sha256 was recorded in every benchmark
manifest and compared with nothing (docs/audits/model-identity-inventory-
2026-11-06.md, "The reranker digest is recorded, never verified"): a changed
or corrupt ONNX file that FlashRank still loads gave ``reranker_state: loaded``
and a different digest, and no surface said so. ``classify_model_digest``
compares the on-disk digest with the digest the committed results carry.

Pure: the digest is computed by the caller (``reranker_model.model_sha256``
or ``infrastructure.reranker_cache.reranker_model_sha256``).

source: docs/audits/model-identity-inventory-2026-11-06.md, remaining slice 3
"""

from __future__ import annotations

from dataclasses import dataclass

# source: benchmarks/results/repro/20261014T232318Z/MANIFEST.json
# ("reranker_model_sha256", git_sha b9d4dd5, reranker_state "loaded"); the
# same value is the only sha256 among the 131 "reranker_model_sha256" entries
# committed under benchmarks/results/ (counted 2026-11-10 at main b3ecf6a).
EXPECTED_MODEL_SHA256 = (
    "d3dd7b09fcf06b0c070081d6819b5effbb40b667bcad78b2d7543400271141d1"
)

ABSENT = "absent"
VERIFIED = "verified"
MISMATCH = "mismatch"


@dataclass(frozen=True)
class ModelIdentity:
    """What the reranker weights on disk are, against the pinned digest."""

    state: str
    sha256: str | None
    expected: str


def classify_model_digest(
    sha256: str | None, expected: str = EXPECTED_MODEL_SHA256
) -> ModelIdentity:
    """Classify an on-disk weights digest.

    precondition: ``sha256`` is the hex sha256 of the weights file, or None
        when the file is absent.
    postcondition: ``state`` is ``absent`` when ``sha256`` is None,
        ``verified`` when it equals ``expected`` (case-insensitive hex), and
        ``mismatch`` otherwise. Nothing else is inferred: a mismatch says the
        bytes differ, not whether they are corrupt or another model.
    """
    if sha256 is None:
        return ModelIdentity(ABSENT, None, expected)
    state = VERIFIED if sha256.lower() == expected.lower() else MISMATCH
    return ModelIdentity(state, sha256, expected)
