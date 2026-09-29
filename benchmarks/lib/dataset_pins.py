"""Pinned benchmark datasets and the preflight that checks a download.

A published score is only comparable when the manifest names the exact
dataset bytes it was computed on. ``reproduce.sh`` has pinned the original
LongMemEval-S file by sha256 since ADR-0859; this module adds the cleaned
LongMemEval-S release and the BEAM revision, and gives every runner one way
to describe the file or revision it actually loaded.

source: Cortex benchmark refresh plan, step 1 (2026-09-30), items (a) and (c).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

# source: https://huggingface.co/api/datasets/xiaowu0162/longmemeval-cleaned/commits/main
# (commit "Upload folder using huggingface_hub", 2025-09-19) and the file's LFS
# entry in /api/datasets/xiaowu0162/longmemeval-cleaned/tree/<commit>, read
# 2026-09-30: oid sha256 and size below.
LME_S_CLEANED_REVISION = "98d7416c24c778c2fee6e6f3006e7a073259d48f"
LME_S_CLEANED_SHA256 = (
    "d6f21ea9d60a0d56f34a05b609c79c88a451d2ae03597821ea3d5a9678c3a442"
)
# source: LFS size of longmemeval_s_cleaned.json at the revision above (2026-09-30).
LME_S_CLEANED_BYTES = 277383467
# source: LongMemEval README and dataset card, "500 evaluation instances" (S variant).
LME_S_QUESTIONS = 500

# source: https://huggingface.co/api/datasets/Mohammadta/BEAM/commits/main, read
# 2026-09-30. HEAD 3205395e is a README-only commit; its data/*.parquet LFS oids
# and README dataset_info are identical to the only data upload, 8b4ddc47
# (2025-11-11), so pinning HEAD loads the same bytes as that upload.
BEAM_REVISION = "3205395e897e7318c7b094ef4e6047b9b82dbb03"

# The keys benchmarks/longmemeval/run_benchmark.py reads from each record.
LME_REQUIRED_KEYS = frozenset(
    {
        "question_id",
        "question_type",
        "question",
        "answer",
        "question_date",
        "answer_session_ids",
        "haystack_sessions",
        "haystack_session_ids",
        "haystack_dates",
    }
)


@dataclass(frozen=True)
class FilePin:
    """One dataset file pinned by repository revision and content."""

    repo: str
    revision: str
    filename: str
    sha256: str
    size: int

    @property
    def url(self) -> str:
        return (
            f"https://huggingface.co/datasets/{self.repo}/resolve/"
            f"{self.revision}/{self.filename}"
        )


LME_S_CLEANED = FilePin(
    repo="xiaowu0162/longmemeval-cleaned",
    revision=LME_S_CLEANED_REVISION,
    filename="longmemeval_s_cleaned.json",
    sha256=LME_S_CLEANED_SHA256,
    size=LME_S_CLEANED_BYTES,
)


class DatasetPinError(RuntimeError):
    """The file on disk is not the pinned dataset."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def file_identity(path: Path) -> dict[str, Any]:
    """The identity a manifest records for a dataset file."""
    return {
        "file": path.name,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def check_pin(path: Path, pin: FilePin) -> dict[str, Any]:
    """Raise unless ``path`` has the pinned size and sha256; return its identity."""
    identity = file_identity(path)
    if identity["bytes"] != pin.size or identity["sha256"] != pin.sha256:
        raise DatasetPinError(
            f"{path} is not {pin.repo}@{pin.revision}/{pin.filename}: "
            f"expected {pin.size} B sha256 {pin.sha256}, got "
            f"{identity['bytes']} B sha256 {identity['sha256']}"
        )
    return {**asdict(pin), **identity}


def check_longmemeval_records(records: list[dict], expected_n: int) -> None:
    """Raise unless there are ``expected_n`` records carrying every read key."""
    if len(records) != expected_n:
        raise DatasetPinError(f"expected {expected_n} records, found {len(records)}")
    for index, record in enumerate(records):
        missing = LME_REQUIRED_KEYS - record.keys()
        if missing:
            raise DatasetPinError(f"record {index} lacks keys {sorted(missing)}")


def preflight_longmemeval(path: Path, pin: FilePin, expected_n: int) -> dict[str, Any]:
    """Check bytes, then record shape, of a pinned LongMemEval file.

    Returns the identity the runner writes into its manifest.
    """
    identity = check_pin(path, pin)
    with path.open(encoding="utf-8") as handle:
        check_longmemeval_records(json.load(handle), expected_n)
    return {**identity, "n_records": expected_n}
