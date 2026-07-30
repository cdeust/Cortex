"""Tests for ingest_findings_artifacts — pure filesystem parsing of AP runs.

Fixture shapes mirror AP's actual Rust structs (verified by reading
automatised-pipeline/src/main.rs, prd_input.rs, prd_validator.rs,
security_gates.rs — see module docstrings for line references), not
guessed JSON.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from mcp_server.handlers.ingest_findings_artifacts import (
    MalformedArtifactError,
    load_finding,
    read_index,
)


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _make_run(tmp_path: Path, run_id: str) -> Path:
    output_dir = tmp_path / "ap-output"
    _write_json(
        output_dir / "runs" / run_id / "index.json",
        {
            "run_id": run_id,
            "started_at": "2026-07-09T00:00:00Z",
            "last_updated_at": "2026-07-09T00:00:00Z",
            "findings": {
                "f1": {
                    "artifact_path": "findings/f1/stage-1.refined.json",
                    "extractor_version": "0.1.0",
                }
            },
        },
    )
    return output_dir


def _write_refined(
    output_dir: Path,
    run_id: str,
    finding_id: str,
    *,
    title="T",
    desc="D",
    source_path: str | None = None,
) -> None:
    _write_json(
        output_dir / "runs" / run_id / "findings" / finding_id / "stage-1.refined.json",
        {
            "extracted": {
                "finding_id": finding_id,
                "title": title,
                "description": desc,
                "relevance_category": "bug",
                "relevance_score": 0.8,
                "extracted_at": "2026-07-09T00:00:00Z",
                "extractor_version": "0.1.0",
                "source_form": "inline" if source_path is None else "file",
                "source_path": source_path,
            },
            "refined_prompt": {"text": "do the thing", "role_hint": "engineer"},
            "refinement": {"added_context": [], "orchestrator_version": "0.1.0"},
        },
    )


def _write_verified(
    output_dir: Path,
    run_id: str,
    finding_id: str,
    *,
    verified=True,
    transcript_digest: str | None = "deadbeef",
) -> None:
    payload = {
        "run_id": run_id,
        "finding_id": finding_id,
        "verified": verified,
        "verified_kind": {
            "schema_ok": True,
            "completeness_ok": True,
            "user_acknowledged": True,
        },
        "finalized_at": "2026-07-09T00:00:00Z",
        "stage1_refined_path": f"findings/{finding_id}/stage-1.refined.json",
        "session_path": f"findings/{finding_id}/stage-2.session.json",
        "digest_algorithm": "sha256",
        "transcript_bytes_at_finalize": 42,
        "turn_count": 2,
        "verifier_version": "0.1.0",
        "completeness_checklist": {"has_title": True},
    }
    if transcript_digest is not None:
        payload["transcript_digest"] = transcript_digest
    _write_json(
        output_dir
        / "runs"
        / run_id
        / "findings"
        / finding_id
        / "stage-2.verified.json",
        payload,
    )


class TestReadIndex:
    def test_reads_findings_map(self, tmp_path):
        output_dir = _make_run(tmp_path, "run1")
        index = read_index(output_dir, "run1")
        assert "f1" in index["findings"]

    def test_missing_index_raises_malformed(self, tmp_path):
        with pytest.raises(MalformedArtifactError):
            read_index(tmp_path / "nope", "run1")

    def test_bad_json_raises_malformed(self, tmp_path):
        output_dir = tmp_path / "ap-output"
        path = output_dir / "runs" / "run1" / "index.json"
        path.parent.mkdir(parents=True)
        path.write_text("{not json", encoding="utf-8")
        with pytest.raises(MalformedArtifactError):
            read_index(output_dir, "run1")

    def test_index_without_findings_key_raises_malformed(self, tmp_path):
        output_dir = tmp_path / "ap-output"
        _write_json(output_dir / "runs" / "run1" / "index.json", {"run_id": "run1"})
        with pytest.raises(MalformedArtifactError):
            read_index(output_dir, "run1")


class TestLoadFindingVerified:
    def test_verified_finding_carries_stage2_receipt(self, tmp_path):
        output_dir = _make_run(tmp_path, "run1")
        _write_refined(output_dir, "run1", "f1")
        _write_verified(output_dir, "run1", "f1")

        finding = load_finding(output_dir, "run1", "f1")

        assert finding.verified is True
        assert finding.title == "T"
        assert len(finding.receipts) == 1
        assert finding.receipts[0].stage == "stage-2"
        assert finding.receipts[0].verdict == "verified"
        # digest = sha256 of the raw artifact bytes, independently recomputable.
        raw = (
            output_dir / "runs" / "run1" / "findings" / "f1" / "stage-2.verified.json"
        ).read_bytes()
        assert finding.receipts[0].digest == hashlib.sha256(raw).hexdigest()

    def test_not_verified_stage2_yields_unverified_finding(self, tmp_path):
        output_dir = _make_run(tmp_path, "run1")
        _write_refined(output_dir, "run1", "f1")
        _write_verified(output_dir, "run1", "f1", verified=False)

        finding = load_finding(output_dir, "run1", "f1")

        assert finding.verified is False
        assert len(finding.receipts) == 1
        assert finding.receipts[0].verdict == "not_verified"


class TestLoadFindingHypothesis:
    def test_no_stage2_yields_hypothesis_with_no_receipts(self, tmp_path):
        output_dir = _make_run(tmp_path, "run1")
        _write_refined(output_dir, "run1", "f1")

        finding = load_finding(output_dir, "run1", "f1")

        assert finding.verified is False
        assert finding.receipts == []


class TestLoadFindingMalformed:
    def test_missing_refined_raises_malformed(self, tmp_path):
        output_dir = _make_run(tmp_path, "run1")
        with pytest.raises(MalformedArtifactError):
            load_finding(output_dir, "run1", "f1")

    def test_corrupt_refined_raises_malformed(self, tmp_path):
        output_dir = _make_run(tmp_path, "run1")
        path = output_dir / "runs" / "run1" / "findings" / "f1" / "stage-1.refined.json"
        path.parent.mkdir(parents=True)
        path.write_text("not json at all", encoding="utf-8")
        with pytest.raises(MalformedArtifactError):
            load_finding(output_dir, "run1", "f1")


class TestTranscriptDigest:
    def test_stage2_transcript_digest_copied_verbatim_when_present(self, tmp_path):
        output_dir = _make_run(tmp_path, "run1")
        _write_refined(output_dir, "run1", "f1")
        _write_verified(output_dir, "run1", "f1", transcript_digest="cafef00d")

        finding = load_finding(output_dir, "run1", "f1")

        assert finding.receipts[0].transcript_digest == "cafef00d"

    def test_stage2_transcript_digest_absent_when_ap_omits_field(self, tmp_path):
        output_dir = _make_run(tmp_path, "run1")
        _write_refined(output_dir, "run1", "f1")
        _write_verified(output_dir, "run1", "f1", transcript_digest=None)

        finding = load_finding(output_dir, "run1", "f1")

        assert finding.receipts[0].transcript_digest is None

    def test_non_stage2_receipts_never_carry_transcript_digest(self, tmp_path):
        output_dir = _make_run(tmp_path, "run1")
        _write_refined(output_dir, "run1", "f1")
        _write_verified(output_dir, "run1", "f1")
        _write_json(
            output_dir
            / "runs"
            / "run1"
            / "findings"
            / "f1"
            / "stage-6.validation.json",
            {"validation_status": "passed", "transcript_digest": "should-be-ignored"},
        )

        finding = load_finding(output_dir, "run1", "f1")

        stage6 = next(r for r in finding.receipts if r.stage == "stage-6")
        assert stage6.transcript_digest is None


class TestSourcePath:
    def test_source_path_carried_when_present(self, tmp_path):
        output_dir = _make_run(tmp_path, "run1")
        _write_refined(output_dir, "run1", "f1", source_path="/abs/path/to/report.json")

        finding = load_finding(output_dir, "run1", "f1")

        assert finding.source_path == "/abs/path/to/report.json"

    def test_source_path_none_when_inline_finding(self, tmp_path):
        output_dir = _make_run(tmp_path, "run1")
        _write_refined(output_dir, "run1", "f1")

        finding = load_finding(output_dir, "run1", "f1")

        assert finding.source_path is None


class TestFilePathsFromStage4:
    def test_extracts_file_part_of_qualified_names(self, tmp_path):
        output_dir = _make_run(tmp_path, "run1")
        _write_refined(output_dir, "run1", "f1")
        _write_verified(output_dir, "run1", "f1")
        _write_json(
            output_dir / "runs" / "run1" / "findings" / "f1" / "stage-4.prd_input.json",
            {
                "report": {
                    "matched_symbols": [
                        {"qualified_name": "src/foo.rs::do_thing"},
                        {"qualified_name": "src/foo.rs::other_thing"},
                        {"qualified_name": "src/bar.rs::helper"},
                    ]
                }
            },
        )

        finding = load_finding(output_dir, "run1", "f1")

        assert finding.file_paths == ["src/foo.rs", "src/bar.rs"]

    def test_no_stage4_yields_empty_file_paths(self, tmp_path):
        output_dir = _make_run(tmp_path, "run1")
        _write_refined(output_dir, "run1", "f1")
        _write_verified(output_dir, "run1", "f1")

        finding = load_finding(output_dir, "run1", "f1")

        assert finding.file_paths == []
