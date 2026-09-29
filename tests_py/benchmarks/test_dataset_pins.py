"""Dataset pins: the cleaned LongMemEval-S file and the BEAM revision."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from benchmarks.beam.data import BEAM_REPO, beam_dataset_identity
from benchmarks.lib.dataset_pins import (
    BEAM_REVISION,
    LME_REQUIRED_KEYS,
    LME_S_CLEANED,
    DatasetPinError,
    check_longmemeval_records,
    check_pin,
    file_identity,
    preflight_longmemeval,
)


def _record() -> dict:
    return {key: [] for key in LME_REQUIRED_KEYS}


def _write(path: Path, records: list[dict]) -> bytes:
    raw = json.dumps(records).encode()
    path.write_bytes(raw)
    return raw


def test_cleaned_pin_matches_the_published_release() -> None:
    assert LME_S_CLEANED.repo == "xiaowu0162/longmemeval-cleaned"
    assert LME_S_CLEANED.revision.startswith("98d7416c")
    assert LME_S_CLEANED.sha256.startswith("d6f21ea9")
    assert LME_S_CLEANED.size == 277383467
    assert LME_S_CLEANED.url.endswith(
        f"/resolve/{LME_S_CLEANED.revision}/longmemeval_s_cleaned.json"
    )


def test_file_identity_hashes_the_bytes(tmp_path: Path) -> None:
    raw = _write(tmp_path / "d.json", [_record()])
    identity = file_identity(tmp_path / "d.json")
    assert identity == {
        "file": "d.json",
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def test_preflight_accepts_the_pinned_file(tmp_path: Path) -> None:
    path = tmp_path / "longmemeval_s_cleaned.json"
    raw = _write(path, [_record(), _record()])
    pin = replace(LME_S_CLEANED, sha256=hashlib.sha256(raw).hexdigest(), size=len(raw))
    identity = preflight_longmemeval(path, pin, expected_n=2)
    assert identity["revision"] == LME_S_CLEANED.revision
    assert identity["n_records"] == 2


def test_preflight_refuses_other_bytes(tmp_path: Path) -> None:
    path = tmp_path / "longmemeval_s_cleaned.json"
    _write(path, [_record()])
    with pytest.raises(DatasetPinError, match="expected 277383467 B"):
        check_pin(path, LME_S_CLEANED)


def test_record_check_refuses_a_wrong_count_or_missing_key() -> None:
    with pytest.raises(DatasetPinError, match="expected 2 records"):
        check_longmemeval_records([_record()], 2)
    broken = _record()
    del broken["haystack_dates"]
    with pytest.raises(DatasetPinError, match="haystack_dates"):
        check_longmemeval_records([broken], 1)


def test_beam_identity_names_the_pinned_revision() -> None:
    assert beam_dataset_identity("100K") == {
        "repo": BEAM_REPO,
        "split": "100K",
        "revision": BEAM_REVISION,
    }
    assert beam_dataset_identity("10M")["revision"] is None
