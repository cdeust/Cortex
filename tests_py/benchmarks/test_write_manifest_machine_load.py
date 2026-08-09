"""machine_load_snapshot in benchmarks.lib.write_manifest (2026-08-10 fix).

Contract under test: every benchmark MANIFEST.json records the machine's
load state (load average, concurrent pytest processes, concurrent Docker
containers) alongside git_sha — not a separate/optional field — so a run
produced under contention can be identified after the fact instead of
requiring someone to have been watching `uptime` live. Prompted by an
incident where a 5-cell trust-factor sweep ran while three other agents'
full pytest suites were active; one cell crashed visibly, but a cell that
merely finished under the same contention would have looked like a clean
result with nothing in the artifact to say otherwise.

Follow-up (same day): the snapshot is taken TWICE per cell — at cell start
(`write_start_snapshot`, written before `start_db`) and at cell end (inside
`build_manifest`) — because a single end-of-run reading cannot tell "ran
under load the whole time" apart from "load spiked right at the end".
"""

from __future__ import annotations

import json

from benchmarks.lib.write_manifest import (
    build_manifest,
    machine_load_snapshot,
    write_start_snapshot,
)

_LOAD_KEYS = {
    "load_average_1m",
    "load_average_5m",
    "load_average_15m",
    "cpu_count",
    "concurrent_pytest_processes",
    "concurrent_docker_containers",
}


class TestMachineLoadSnapshot:
    def test_returns_all_expected_keys(self):
        snap = machine_load_snapshot()
        assert set(snap) == _LOAD_KEYS

    def test_load_averages_are_nonnegative_floats_on_a_posix_machine(self):
        snap = machine_load_snapshot()
        for key in ("load_average_1m", "load_average_5m", "load_average_15m"):
            assert isinstance(snap[key], float)
            assert snap[key] >= 0.0

    def test_cpu_count_is_a_positive_int(self):
        snap = machine_load_snapshot()
        assert isinstance(snap["cpu_count"], int)
        assert snap["cpu_count"] > 0

    def test_pytest_process_count_sees_the_process_running_this_test(self):
        """The suite executing this assertion IS a pytest process, so the
        count must be >= 1 — a fixed proof the probe is not silently
        returning zero/None while pytest is demonstrably running."""
        snap = machine_load_snapshot()
        assert snap["concurrent_pytest_processes"] is not None
        assert snap["concurrent_pytest_processes"] >= 1

    def test_docker_container_count_is_an_int_or_none(self):
        """None only when the docker CLI itself is unavailable/unreachable —
        never raises, matching every other probe in this module."""
        snap = machine_load_snapshot()
        count = snap["concurrent_docker_containers"]
        assert count is None or (isinstance(count, int) and count >= 0)


class TestBuildManifestIncludesMachineLoad:
    def test_machine_load_at_end_sits_alongside_git_sha(self, tmp_path):
        manifest = build_manifest(
            str(tmp_path),
            "deadbeef",
            "dataset-sha",
            "pgvector/pgvector:pg16",
            "test-container",
            "5432",
            "1",
        )
        assert "git_sha" in manifest
        assert "machine_load_at_end" in manifest
        assert set(manifest["machine_load_at_end"]) == _LOAD_KEYS

    def test_machine_load_at_start_is_none_when_no_snapshot_was_taken(self, tmp_path):
        manifest = build_manifest(
            str(tmp_path),
            "deadbeef",
            "dataset-sha",
            "pgvector/pgvector:pg16",
            "test-container",
            "5432",
            "1",
        )
        assert manifest["machine_load_at_start"] is None

    def test_machine_load_at_start_is_populated_when_a_snapshot_was_taken(
        self, tmp_path
    ):
        write_start_snapshot(str(tmp_path))
        manifest = build_manifest(
            str(tmp_path),
            "deadbeef",
            "dataset-sha",
            "pgvector/pgvector:pg16",
            "test-container",
            "5432",
            "1",
        )
        assert manifest["machine_load_at_start"] is not None
        assert set(manifest["machine_load_at_start"]) == _LOAD_KEYS

    def test_start_snapshot_file_is_excluded_from_results_files(self, tmp_path):
        write_start_snapshot(str(tmp_path))
        manifest = build_manifest(
            str(tmp_path),
            "deadbeef",
            "dataset-sha",
            "pgvector/pgvector:pg16",
            "test-container",
            "5432",
            "1",
        )
        assert "START_SNAPSHOT.json" not in manifest["results_files"]


class TestWriteStartSnapshot:
    def test_writes_a_readable_json_file_with_a_timestamp_and_load(self, tmp_path):
        out = write_start_snapshot(str(tmp_path))
        assert out.exists()
        payload = json.loads(out.read_text())
        assert "captured_at_utc" in payload
        assert set(payload["machine_load"]) == _LOAD_KEYS
