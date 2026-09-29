"""The run MANIFEST names the dataset behind every leg's score."""

from __future__ import annotations

import json
from pathlib import Path

from benchmarks.lib.write_manifest import _dataset_fields


def test_dataset_fields_read_each_leg_manifest(tmp_path: Path) -> None:
    cleaned = {"repo": "xiaowu0162/longmemeval-cleaned", "sha256": "d6f2"}
    (tmp_path / "longmemeval-s-cleaned.json").write_text(
        json.dumps({"overall_mrr": 0.9, "manifest": {"dataset": cleaned}})
    )
    (tmp_path / "beam-100K.json").write_text(
        json.dumps({"manifest": {"dataset": {"revision": "3205395e"}}})
    )
    (tmp_path / "decision-ids.json").write_text(json.dumps({"hits": 3}))
    (tmp_path / "START_SNAPSHOT.json").write_text("{}")
    (tmp_path / "MANIFEST.json").write_text("{}")
    (tmp_path / "locomo.queries.jsonl").write_text("{}\n")
    (tmp_path / "broken.json").write_text("{not json")

    assert _dataset_fields(str(tmp_path)) == {
        "datasets": {
            "beam-100K": {"revision": "3205395e"},
            "decision-ids": None,
            "longmemeval-s-cleaned": cleaned,
        }
    }
