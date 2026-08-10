"""benchmarks.lib.disk_space_snapshot (2026-08-10 fix).

Contract under test: `disk_space_snapshot()` reports free/total bytes on
the repo-root filesystem (where benchmark datasets, throwaway test
databases, and HF cache land) and, best-effort, on Docker's storage root —
never raising, matching every other probe in this codebase's manifest
tooling. See the module's own docstring for the disk-exhaustion incident
motivating this (leaked test databases filled a shared machine's disk to
100% mid-benchmark, taking PostgreSQL down with no trace in the artifact).
"""

from __future__ import annotations

from benchmarks.lib.disk_space_snapshot import disk_space_snapshot


class TestDiskSpaceSnapshot:
    def test_returns_repo_root_and_docker_root_keys(self):
        snap = disk_space_snapshot()
        assert set(snap) == {"repo_root", "docker_root"}

    def test_repo_root_is_populated_on_a_reachable_filesystem(self):
        """The repo itself is on disk right now, so this must never be
        None in a test-running environment."""
        snap = disk_space_snapshot()
        assert snap["repo_root"] is not None
        assert set(snap["repo_root"]) == {"path", "free_bytes", "total_bytes"}

    def test_repo_root_free_and_total_are_consistent_positive_ints(self):
        snap = disk_space_snapshot()
        repo_root = snap["repo_root"]
        assert isinstance(repo_root["free_bytes"], int)
        assert isinstance(repo_root["total_bytes"], int)
        assert 0 <= repo_root["free_bytes"] <= repo_root["total_bytes"]

    def test_docker_root_is_a_dict_or_none(self):
        """None only when the docker CLI is unavailable/unreachable or its
        reported root path can't be statted -- never raises."""
        snap = disk_space_snapshot()
        docker_root = snap["docker_root"]
        assert docker_root is None or set(docker_root) == {
            "path",
            "free_bytes",
            "total_bytes",
        }
