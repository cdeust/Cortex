"""D5 — per-domain profile split: migration + write-amplification bound.

Prior behaviour: all domain profiles lived in ``~/.claude/methodology/profiles.json``.
Every ``record_session_end`` re-read and re-wrote the whole file — at 1000
domains that's ~10 MB of I/O per session end.

New behaviour:
    - Domains live in ``~/.claude/methodology/domains/<domain-id>.json``.
    - ``~/.claude/methodology/index.json`` holds globals + list of domain ids.
    - ``save_profile(domain_id, profile)`` rewrites one file, not the world.
    - Legacy migration: on first load the old single-file ``profiles.json``
      is split and renamed to ``profiles.json.v1_backup``.

Three invariants tested:
    1. Migration from legacy single file is lossless and idempotent.
    2. ``save_profile`` does NOT rewrite any other domain's file.
    3. ``load_profiles`` output is equivalent pre- and post- migration
       (so ``list_domains`` and other handlers keep working).
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from mcp_server.infrastructure import profile_store


@pytest.fixture
def isolated_methodology(tmp_path, monkeypatch):
    """Patch all paths to point at a fresh tmp directory per test."""
    methodology = tmp_path / "methodology"
    methodology.mkdir()
    domains_dir = methodology / "domains"
    profiles_path = methodology / "profiles.json"
    index_path = methodology / "index.json"
    legacy_backup = Path(str(profiles_path) + ".v1_backup")

    monkeypatch.setattr(profile_store, "METHODOLOGY_DIR", methodology)
    monkeypatch.setattr(profile_store, "DOMAINS_DIR", domains_dir)
    monkeypatch.setattr(profile_store, "PROFILES_PATH", profiles_path)
    monkeypatch.setattr(profile_store, "INDEX_PATH", index_path)
    monkeypatch.setattr(profile_store, "LEGACY_BACKUP_PATH", legacy_backup)

    return {
        "methodology": methodology,
        "domains": domains_dir,
        "profiles": profiles_path,
        "index": index_path,
        "legacy_backup": legacy_backup,
    }


def _make_profile(domain_id: str, tools: int) -> dict:
    """Make a realistic-shaped domain profile for tests."""
    return {
        "label": domain_id.replace("-", " ").title(),
        "tools": {f"tool_{i}": i * 0.1 for i in range(tools)},
        "keywords": [f"kw_{i}" for i in range(tools)],
        "cognitive_style": {"active-reflective": 0.3},
    }


class TestLegacyMigration:
    """On first load, a legacy single-file profiles.json is split."""

    def test_legacy_file_is_split_into_per_domain_files(
        self, isolated_methodology
    ):
        paths = isolated_methodology
        legacy = {
            "version": 2,
            "updatedAt": "2026-04-16T00:00:00Z",
            "globalStyle": {"active-reflective": 0.2},
            "domains": {
                "cortex": _make_profile("cortex", 3),
                "beam": _make_profile("beam", 2),
                "alpha": _make_profile("alpha", 1),
            },
        }
        import json

        paths["profiles"].write_text(json.dumps(legacy))

        # Trigger migration.
        loaded = profile_store.load_profiles()

        # Each domain has its own file.
        assert (paths["domains"] / "cortex.json").exists()
        assert (paths["domains"] / "beam.json").exists()
        assert (paths["domains"] / "alpha.json").exists()
        # Index exists with the domain ids sorted.
        assert paths["index"].exists()
        idx = json.loads(paths["index"].read_text())
        assert idx["domain_ids"] == ["alpha", "beam", "cortex"]
        assert idx["globalStyle"] == {"active-reflective": 0.2}
        # Legacy file is renamed, not kept at the old location.
        assert not paths["profiles"].exists()
        assert paths["legacy_backup"].exists()
        # Loaded profiles contain all three.
        assert set(loaded["domains"].keys()) == {"cortex", "beam", "alpha"}
        assert loaded["domains"]["cortex"]["label"] == "Cortex"

    def test_migration_is_idempotent(self, isolated_methodology):
        """Calling load_profiles twice is safe — second call is a no-op."""
        paths = isolated_methodology
        import json

        paths["profiles"].write_text(
            json.dumps(
                {
                    "version": 2,
                    "domains": {"cortex": _make_profile("cortex", 2)},
                }
            )
        )

        first = profile_store.load_profiles()
        # Second call should still succeed — no legacy file to migrate,
        # just read the already-split structure.
        second = profile_store.load_profiles()
        assert first["domains"].keys() == second["domains"].keys()
        assert first["domains"]["cortex"] == second["domains"]["cortex"]


class TestTargetedSaveAmplification:
    """save_profile must NOT rewrite other domains' files."""

    def test_save_one_does_not_touch_other_files(self, isolated_methodology):
        paths = isolated_methodology
        # Seed three domains via save_profile.
        profile_store.save_profile("alpha", _make_profile("alpha", 1))
        profile_store.save_profile("beta", _make_profile("beta", 2))
        profile_store.save_profile("gamma", _make_profile("gamma", 3))

        alpha_path = paths["domains"] / "alpha.json"
        beta_path = paths["domains"] / "beta.json"
        gamma_path = paths["domains"] / "gamma.json"

        # Capture mtimes.
        mtime_alpha_before = alpha_path.stat().st_mtime_ns
        mtime_beta_before = beta_path.stat().st_mtime_ns
        mtime_gamma_before = gamma_path.stat().st_mtime_ns

        # Filesystem mtime resolution on macOS can be 1 µs; some
        # filesystems are coarser. Sleep a comfortable margin.
        time.sleep(0.02)

        # Update ONLY gamma.
        updated = _make_profile("gamma", 5)
        updated["new_field"] = True
        profile_store.save_profile("gamma", updated)

        mtime_alpha_after = alpha_path.stat().st_mtime_ns
        mtime_beta_after = beta_path.stat().st_mtime_ns
        mtime_gamma_after = gamma_path.stat().st_mtime_ns

        # Alpha and beta files were NOT touched.
        assert mtime_alpha_after == mtime_alpha_before, (
            "alpha.json was rewritten — save_profile leaked to other domains"
        )
        assert mtime_beta_after == mtime_beta_before, (
            "beta.json was rewritten — save_profile leaked to other domains"
        )
        # Gamma was updated.
        assert mtime_gamma_after > mtime_gamma_before
        # Content is the new one.
        import json

        assert json.loads(gamma_path.read_text())["new_field"] is True

    def test_save_profile_updates_index(self, isolated_methodology):
        """New domains appear in the index."""
        profile_store.save_profile("newdomain", _make_profile("newdomain", 1))
        idx = profile_store._ensure_index()
        assert "newdomain" in idx["domain_ids"]
        # updatedAt is refreshed.
        assert idx["updatedAt"] is not None

    def test_load_profile_returns_single_domain(self, isolated_methodology):
        """load_profile reads one file — other domains' state is irrelevant."""
        profile_store.save_profile("x", _make_profile("x", 1))
        profile_store.save_profile("y", _make_profile("y", 2))
        got = profile_store.load_profile("x")
        assert got is not None
        assert got["label"] == "X"

    def test_load_profile_unknown_returns_none(self, isolated_methodology):
        assert profile_store.load_profile("nonexistent") is None

    def test_load_profile_rejects_unsafe_ids(self, isolated_methodology):
        """Path-traversal attempt is blocked."""
        assert profile_store.load_profile("../etc/passwd") is None
        assert profile_store.load_profile("a/b") is None


class TestListDomainsEquivalence:
    """load_profiles output is equivalent pre- and post-migration."""

    def test_load_profiles_shape_post_migration_matches_legacy(
        self, isolated_methodology
    ):
        """After migration, load_profiles produces the same dict shape."""
        paths = isolated_methodology
        legacy_data = {
            "version": 2,
            "updatedAt": "2026-04-16T00:00:00Z",
            "globalStyle": None,
            "domains": {
                "cortex": _make_profile("cortex", 3),
                "beam": _make_profile("beam", 1),
            },
        }
        import json

        paths["profiles"].write_text(json.dumps(legacy_data))

        loaded = profile_store.load_profiles()

        # Top-level keys match.
        assert set(loaded.keys()) == {"version", "updatedAt", "globalStyle", "domains"}
        # Domain contents match (round-trip).
        assert loaded["domains"]["cortex"] == legacy_data["domains"]["cortex"]
        assert loaded["domains"]["beam"] == legacy_data["domains"]["beam"]

    def test_save_profiles_still_works_as_bulk_write(
        self, isolated_methodology
    ):
        """Legacy bulk save_profiles still produces per-domain files."""
        profiles = profile_store.empty_profiles()
        profiles["domains"]["one"] = _make_profile("one", 1)
        profiles["domains"]["two"] = _make_profile("two", 2)

        profile_store.save_profiles(profiles)

        paths = isolated_methodology
        assert (paths["domains"] / "one.json").exists()
        assert (paths["domains"] / "two.json").exists()
        # Index lists both.
        import json

        idx = json.loads(paths["index"].read_text())
        assert set(idx["domain_ids"]) == {"one", "two"}

    def test_empty_state_returns_empty_profiles(self, isolated_methodology):
        """No files at all → load_profiles returns the empty v2 structure."""
        p = profile_store.load_profiles()
        assert p["version"] == 2
        assert p["domains"] == {}
