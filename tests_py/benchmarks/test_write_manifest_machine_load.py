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
"""

from __future__ import annotations

from benchmarks.lib.write_manifest import build_manifest, machine_load_snapshot


class TestMachineLoadSnapshot:
    def test_returns_all_expected_keys(self):
        snap = machine_load_snapshot()
        assert set(snap) == {
            "load_average_1m",
            "load_average_5m",
            "load_average_15m",
            "cpu_count",
            "concurrent_pytest_processes",
            "concurrent_docker_containers",
        }

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
    def test_machine_load_sits_alongside_git_sha(self, tmp_path):
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
        assert "machine_load" in manifest
        assert set(manifest["machine_load"]) == {
            "load_average_1m",
            "load_average_5m",
            "load_average_15m",
            "cpu_count",
            "concurrent_pytest_processes",
            "concurrent_docker_containers",
        }
