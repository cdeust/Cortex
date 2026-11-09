"""Tests for scripts/native_receipt.py, the native receipt schema (#730)."""

from __future__ import annotations

import copy
import json

import pytest

from scripts import native_receipt as nr

DIGEST = "a" * 64


def _receipt() -> dict:
    return {
        "schema": nr.SCHEMA,
        "artifact": {
            "kind": "wheel",
            "version": "4.23.4",
            "revision": None,
            "modified": False,
            "members_digest": DIGEST,
        },
        "platform": {"os": "macOS", "os_version": "26.1", "arch": "arm64"},
        "backend": "managed PostgreSQL",
        "hosts": [{"name": "Claude Code", "version": "2.3.0"}],
        "checks": [
            {
                "id": "startup-context",
                "host": "Claude Code",
                "outcome": "passed",
                "artifact_digest": DIGEST,
                "evidence": "SessionStart injected the project briefing",
            }
        ],
    }


def test_valid_wheel_receipt_has_no_errors_and_is_distributed():
    receipt = _receipt()
    assert nr.validate(receipt) == []
    assert nr.is_distributed(receipt) is True


def test_check_run_on_another_artifact_is_refused():
    receipt = _receipt()
    receipt["checks"][0]["artifact_digest"] = "b" * 64
    assert nr.validate(receipt) == [
        "checks[0].artifact_digest: differs from artifact.members_digest"
    ]


def test_check_from_an_unlisted_host_is_refused():
    receipt = _receipt()
    receipt["checks"][0]["host"] = "Codex"
    assert nr.validate(receipt) == ["checks[0].host: 'Codex' is not listed in hosts"]


@pytest.mark.parametrize(
    ("path", "value", "error"),
    [
        (("artifact", "kind"), "zip", "artifact.kind: 'zip' is not one of"),
        (("artifact", "members_digest"), "abc", "artifact.members_digest: not a"),
        (("artifact", "revision"), "deadbeef", "artifact.revision: a wheel has"),
        (("artifact", "modified"), "no", "artifact.modified: expected"),
    ],
)
def test_artifact_identity_errors(path, value, error):
    receipt = _receipt()
    receipt[path[0]][path[1]] = value
    if path[1] == "members_digest":
        # The check names the same (malformed) digest: only the format is wrong.
        receipt["checks"][0]["artifact_digest"] = value
    errors = nr.validate(receipt)
    assert len(errors) == 1 and errors[0].startswith(error)


def test_unknown_outcome_and_empty_evidence_are_refused():
    receipt = _receipt()
    receipt["checks"][0].update(outcome="skipped", evidence="  ")
    assert nr.validate(receipt) == [
        "checks[0].outcome: 'skipped' not in ('passed', 'failed')",
        "checks[0].evidence: expected a non-empty string",
    ]


@pytest.mark.parametrize("evidence", [None, [], {}, 0])
def test_evidence_that_is_not_text_is_refused(evidence):
    # str(None) is "None": stringifying would count a null as evidence (#948).
    receipt = _receipt()
    receipt["checks"][0]["evidence"] = evidence
    assert nr.validate(receipt) == ["checks[0].evidence: expected a non-empty string"]


def test_null_identity_fields_are_all_refused():
    receipt = _receipt()
    receipt["artifact"]["version"] = None
    receipt["platform"].update(os=None, os_version="", arch=None)
    receipt["backend"] = None
    assert nr.validate(receipt) == ["backend: expected a non-empty string"]
    receipt["backend"] = "managed PostgreSQL"
    assert nr.validate(receipt) == [
        "artifact.version: expected a non-empty string",
        "platform.os: expected a non-empty string",
        "platform.os_version: expected a non-empty string",
        "platform.arch: expected a non-empty string",
    ]


@pytest.mark.parametrize("key", ["name", "version"])
def test_null_host_identity_is_refused(key):
    receipt = _receipt()
    receipt["hosts"][0][key] = None
    assert nr.validate(receipt) == [f"hosts[0].{key}: expected a non-empty string"]


def test_unhashable_check_host_is_an_error_not_a_crash():
    receipt = _receipt()
    receipt["checks"][0]["host"] = ["Claude Code"]
    assert nr.validate(receipt) == [
        "checks[0].host: ['Claude Code'] is not listed in hosts"
    ]


def test_a_host_name_listed_twice_is_refused():
    # Two versions under one name: a check could not say which one ran.
    receipt = _receipt()
    receipt["hosts"].append({"name": "Claude Code", "version": "2.3.1"})
    assert nr.validate(receipt) == ["hosts[1].name: 'Claude Code' is listed twice"]


def test_source_tree_revision_must_be_text_or_null():
    receipt = _receipt()
    receipt["artifact"].update(kind="source-tree", revision="", modified=False)
    assert nr.validate(receipt) == [
        "artifact.revision: expected a non-empty string or null"
    ]
    receipt["artifact"]["revision"] = None
    assert nr.validate(receipt) == []


def test_missing_sections_are_all_named():
    receipt = _receipt()
    del receipt["platform"]["arch"], receipt["backend"]
    receipt["checks"] = []
    assert nr.validate(receipt) == [
        "platform.arch: missing",
        "backend: missing",
        "checks: expected a non-empty list",
    ]


def test_wrong_schema_is_refused_first():
    assert nr.validate({"schema": "v0"}) == [
        f"schema: expected {nr.SCHEMA!r}, got 'v0'"
    ]
    assert nr.validate([]) == ["receipt: expected a JSON object"]


def test_modified_source_tree_is_source_evidence_only():
    receipt = _receipt()
    receipt["artifact"].update(kind="source-tree", revision="0" * 40, modified=True)
    assert nr.validate(receipt) == []
    assert nr.is_distributed(receipt) is False


def test_coverage_names_passed_failed_and_missing_journeys():
    receipt = _receipt()
    failed = copy.deepcopy(receipt["checks"][0])
    failed.update(id="unicode", outcome="failed")
    passed_again = copy.deepcopy(failed)
    passed_again["outcome"] = "passed"
    receipt["checks"] += [failed, passed_again]
    report = nr.coverage(receipt)
    assert report["passed"] == ["startup-context"]
    assert report["failed"] == ["unicode"]
    assert len(report["missing"]) == len(nr.REQUIRED_CHECKS) - 2


def test_cli_exit_codes(tmp_path, capsys):
    good = tmp_path / "good.json"
    good.write_text(json.dumps(_receipt()), encoding="utf-8")
    assert nr.main([str(good)]) == 0
    assert json.loads(capsys.readouterr().out)["distributed"] is True
    bad = _receipt()
    bad["checks"][0]["artifact_digest"] = "c" * 64
    good.write_text(json.dumps(bad), encoding="utf-8")
    assert nr.main([str(good)]) == 1
    good.write_text("{", encoding="utf-8")
    assert nr.main([str(good)]) == 2
