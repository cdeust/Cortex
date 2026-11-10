"""Reranker weights digest against the pinned one (issue #734, slice 3)."""

from __future__ import annotations

import json
from pathlib import Path

from mcp_server.core.reranker_identity import (
    ABSENT,
    EXPECTED_MODEL_SHA256,
    MISMATCH,
    VERIFIED,
    classify_model_digest,
)

_REPO = Path(__file__).resolve().parents[2]
_SOURCE = _REPO / "benchmarks/results/repro/20261014T232318Z/MANIFEST.json"


def test_absent_file_is_absent():
    identity = classify_model_digest(None)
    assert (identity.state, identity.sha256) == (ABSENT, None)
    assert identity.expected == EXPECTED_MODEL_SHA256


def test_pinned_digest_is_verified_whatever_the_hex_case():
    assert classify_model_digest(EXPECTED_MODEL_SHA256).state == VERIFIED
    assert classify_model_digest(EXPECTED_MODEL_SHA256.upper()).state == VERIFIED


def test_other_digest_is_a_mismatch_and_keeps_both_values():
    other = "0" * 64
    identity = classify_model_digest(other)
    assert (identity.state, identity.sha256) == (MISMATCH, other)
    assert identity.expected == EXPECTED_MODEL_SHA256


def test_pin_is_the_digest_the_cited_results_carry():
    manifest = json.loads(_SOURCE.read_bytes())
    assert manifest["reranker_state"] == "loaded"
    assert manifest["reranker_model_sha256"] == EXPECTED_MODEL_SHA256
