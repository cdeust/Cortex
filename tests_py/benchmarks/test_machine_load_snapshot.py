"""benchmarks.lib.machine_load_snapshot (2026-08-10 fix, split out of
write_manifest.py to satisfy the 40-line method cap — CLAUDE.md § Code
Style). See that module's docstring for the incident motivating it.
"""

from __future__ import annotations

from benchmarks.lib.machine_load_snapshot import machine_load_snapshot

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
        returning zero/None while pytest is demonstrably running. Pinned by
        the COLUMNS-truncation fix (2026-08-10): this exact assertion is
        what caught the bug on GitHub's Linux CI runner."""
        snap = machine_load_snapshot()
        assert snap["concurrent_pytest_processes"] is not None
        assert snap["concurrent_pytest_processes"] >= 1

    def test_docker_container_count_is_an_int_or_none(self):
        """None only when the docker CLI itself is unavailable/unreachable —
        never raises, matching every other probe in this module."""
        snap = machine_load_snapshot()
        count = snap["concurrent_docker_containers"]
        assert count is None or (isinstance(count, int) and count >= 0)
