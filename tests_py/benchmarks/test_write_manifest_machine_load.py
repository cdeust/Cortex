"""write_manifest.py's start/end machine-load + disk-space wiring
(2026-08-10 fix).

Contract under test: every benchmark MANIFEST.json records BOTH the
machine's load state and its free disk space, at cell start AND cell end,
alongside git_sha — not a separate/optional field — so a run produced
under CPU contention or disk exhaustion can be identified after the fact
instead of requiring someone to have been watching `uptime`/`df` live.

Two incidents motivate this (full narrative in
benchmarks/lib/machine_load_snapshot.py and
benchmarks/lib/disk_space_snapshot.py's module docstrings): a 5-cell
trust-factor sweep ran while three other agents' full pytest suites were
active (one cell crashed visibly, but a cell that merely finished under
the same contention would have looked clean); and leaked throwaway test
databases filled the host disk to 100% on a neighboring session sharing
the same machine, taking PostgreSQL down mid-measurement.

The probe functions themselves (`machine_load_snapshot`,
`disk_space_snapshot`) are tested in their own modules'
tests_py/benchmarks/test_machine_load_snapshot.py and
tests_py/benchmarks/test_disk_space_snapshot.py — this file only tests
`write_manifest.py`'s wiring of the two snapshot points into MANIFEST.json.
"""

from __future__ import annotations

import json

from benchmarks.lib.machine_load_snapshot import machine_load_snapshot
from benchmarks.lib.write_manifest import build_manifest, write_start_snapshot

_LOAD_KEYS = {
    "load_average_1m",
    "load_average_5m",
    "load_average_15m",
    "cpu_count",
    "concurrent_pytest_processes",
    "concurrent_docker_containers",
}


def _build(tmp_path):
    return build_manifest(
        str(tmp_path),
        "deadbeef",
        "dataset-sha",
        "pgvector/pgvector:pg16",
        "test-container",
        "5432",
        "1",
    )


class TestBuildManifestAtEndFields:
    def test_machine_load_at_end_sits_alongside_git_sha(self, tmp_path):
        manifest = _build(tmp_path)
        assert "git_sha" in manifest
        assert "machine_load_at_end" in manifest
        assert set(manifest["machine_load_at_end"]) == _LOAD_KEYS

    def test_disk_space_at_end_sits_alongside_git_sha(self, tmp_path):
        manifest = _build(tmp_path)
        assert "disk_space_at_end" in manifest
        assert set(manifest["disk_space_at_end"]) == {"repo_root", "docker_root"}


class TestBuildManifestAtStartFields:
    def test_both_at_start_fields_are_none_when_no_snapshot_was_taken(self, tmp_path):
        manifest = _build(tmp_path)
        assert manifest["machine_load_at_start"] is None
        assert manifest["disk_space_at_start"] is None

    def test_both_at_start_fields_are_populated_when_a_snapshot_was_taken(
        self, tmp_path
    ):
        write_start_snapshot(str(tmp_path))
        manifest = _build(tmp_path)
        assert set(manifest["machine_load_at_start"]) == _LOAD_KEYS
        assert set(manifest["disk_space_at_start"]) == {"repo_root", "docker_root"}

    def test_at_start_fields_are_the_snapshot_taken_at_start_not_a_fresh_read(
        self, tmp_path
    ):
        """The manifest must read back the PERSISTED start snapshot, not
        silently re-sample -- otherwise `_at_start` would always equal
        `_at_end` and the two-point design would measure nothing."""
        write_start_snapshot(str(tmp_path))
        persisted = json.loads((tmp_path / "START_SNAPSHOT.json").read_text())
        manifest = _build(tmp_path)
        assert manifest["machine_load_at_start"] == persisted["machine_load"]
        assert manifest["disk_space_at_start"] == persisted["disk_space"]


class TestResultsFilesExclusion:
    def test_start_snapshot_file_is_excluded_from_results_files(self, tmp_path):
        write_start_snapshot(str(tmp_path))
        manifest = _build(tmp_path)
        assert "START_SNAPSHOT.json" not in manifest["results_files"]


class TestWriteStartSnapshot:
    def test_writes_a_readable_json_file_with_a_timestamp_load_and_disk(self, tmp_path):
        out = write_start_snapshot(str(tmp_path))
        assert out.exists()
        payload = json.loads(out.read_text())
        assert "captured_at_utc" in payload
        assert set(payload["machine_load"]) == _LOAD_KEYS
        assert set(payload["disk_space"]) == {"repo_root", "docker_root"}

    def test_matches_a_direct_probe_call_in_shape(self, tmp_path):
        """Not a value-equality check (load/disk drift between calls) --
        confirms write_start_snapshot persists the SAME shape
        machine_load_snapshot() itself returns, not a re-derived one."""
        out = write_start_snapshot(str(tmp_path))
        payload = json.loads(out.read_text())
        assert set(payload["machine_load"]) == set(machine_load_snapshot())
