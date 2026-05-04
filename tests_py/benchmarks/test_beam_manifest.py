"""Manifest schema invariants — protocol §10.

Tests:
  1. ``build_manifest`` populates every required §10 top-level field.
  2. ``write_manifest`` refuses to write a blob containing an API-key prefix.
  3. ``audit_no_secrets`` correctly flags suspected key material.
  4. ``update_cost_tracking`` is read-modify-write atomic from a single writer.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmarks.llm_head_to_head import manifest as M


@pytest.fixture
def fake_prompts(tmp_path: Path) -> tuple[Path, Path]:
    """Create stub prompt files; SHA-256 of these is recorded."""
    a = tmp_path / "answer.md"
    b = tmp_path / "judge.md"
    a.write_text("answer prompt body\n")
    b.write_text("judge prompt body\n")
    return a, b


@pytest.fixture
def fake_lockfile(tmp_path: Path) -> Path:
    p = tmp_path / "uv.lock"
    p.write_text("# stub lockfile\n")
    return p


def test_required_fields_present(tmp_path, fake_prompts, fake_lockfile):
    a, b = fake_prompts
    m = M.build_manifest(
        run_id="testrun-001",
        repo_root=tmp_path,
        generator_models={
            "haiku_4_5": M.ManifestModelEntry(
                api="anthropic", model_id="claude-haiku-4-5-20251001"
            )
        },
        judge_models={
            "gpt4o": M.ManifestModelEntry(api="openai", model_id="gpt-4o-2024-11-20")
        },
        judge_mode="cross_vendor",
        item_count=196,
        conditions=["A", "B", "C", "D"],
        pricing_snapshot_sha="0" * 64,
        answer_prompt_path=a,
        judge_prompt_path=b,
        package_lockfile_path=fake_lockfile,
    )
    out_dir = tmp_path / "results" / "testrun-001"
    out = M.write_manifest(m, out_dir)
    blob = json.loads(out.read_text())

    for k in M.REQUIRED_TOP_LEVEL_KEYS:
        assert k in blob, f"required §10 field missing: {k}"

    # Specific structural checks.
    assert blob["item_count"] == 196
    assert blob["cells_total"] == 196 * 4 * 1
    assert blob["judge_mode"] == "cross_vendor"
    assert blob["conditions"] == ["A", "B", "C", "D"]
    assert blob["stats"]["shuffle_seed_base"] == 20260501
    assert blob["stats"]["bootstrap_seed"] == 20260503
    assert "answer_prompt_sha256" in blob["prompts"]
    assert len(blob["prompts"]["answer_prompt_sha256"]) == 64


def test_audit_flags_anthropic_prefix():
    findings = M.audit_no_secrets({"key": "sk-ant-1234567890"})
    assert findings, "audit must flag sk- prefix"
    assert any("sk-" in f for f in findings)


def test_audit_flags_google_prefix():
    findings = M.audit_no_secrets({"creds": "AIzaSyDeadbeefDeadbeefDeadbeef"})
    assert findings


def test_audit_clean_for_normal_strings():
    findings = M.audit_no_secrets({
        "ok": "claude-haiku-4-5-20251001",
        "model": "gpt-4o-2024-11-20",
        "nested": {"inner": "no secrets here"},
    })
    assert findings == []


def test_write_refuses_to_serialize_keys(tmp_path, fake_prompts, fake_lockfile):
    """Defence in depth: even if a key sneaks in, write_manifest aborts."""
    a, b = fake_prompts
    m = M.build_manifest(
        run_id="testrun-leak",
        repo_root=tmp_path,
        generator_models={},
        judge_models={},
        judge_mode="cross_vendor",
        item_count=1,
        conditions=["A"],
        pricing_snapshot_sha="0" * 64,
        answer_prompt_path=a,
        judge_prompt_path=b,
        package_lockfile_path=fake_lockfile,
    )
    # Inject a "leaked" key into the cost-tracking dict (simulating bug).
    m.cost_tracking["accidentally_leaked"] = "sk-ant-LEAK_LEAK_LEAK"
    out_dir = tmp_path / "results"
    with pytest.raises(RuntimeError, match="suspected API key"):
        M.write_manifest(m, out_dir)


def test_cost_tracking_increment(tmp_path, fake_prompts, fake_lockfile):
    a, b = fake_prompts
    m = M.build_manifest(
        run_id="testrun-cost",
        repo_root=tmp_path,
        generator_models={},
        judge_models={},
        judge_mode="single_judge_opus",
        item_count=2,
        conditions=["A"],
        pricing_snapshot_sha="0" * 64,
        answer_prompt_path=a,
        judge_prompt_path=b,
        package_lockfile_path=fake_lockfile,
    )
    out_dir = tmp_path / "results" / "testrun-cost"
    path = M.write_manifest(m, out_dir)

    M.update_cost_tracking(path, add_input_tokens=100, add_output_tokens=20, add_usd=0.01)
    M.update_cost_tracking(path, add_input_tokens=50, add_output_tokens=10, add_usd=0.005)

    blob = json.loads(path.read_text())
    assert blob["cost_tracking"]["input_tokens_total"] == 150
    assert blob["cost_tracking"]["output_tokens_total"] == 30
    assert abs(blob["cost_tracking"]["estimated_usd"] - 0.015) < 1e-9


def test_item_result_appends_jsonl(tmp_path):
    out_dir = tmp_path / "items-test"
    out_dir.mkdir()
    line = M.ItemResultLine(
        question_id="q-001",
        ability="information_extraction",
        condition="C",
        generator_model="claude-haiku-4-5-20251001",
        generator_response="42",
        judge_label="correct",
        input_tokens=4500,
        output_tokens=10,
        retry_count=0,
        estimated_usd=0.0046,
        wall_time_s=2.3,
    )
    M.append_item_result(out_dir, line)
    M.append_item_result(out_dir, line)
    contents = (out_dir / "items.jsonl").read_text().strip().splitlines()
    assert len(contents) == 2
    parsed = json.loads(contents[0])
    assert parsed["question_id"] == "q-001"
    assert parsed["condition"] == "C"
    assert parsed["judge_label"] == "correct"
