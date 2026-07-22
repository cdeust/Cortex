"""Tests for infrastructure/backend_marker.py — persisted backend selection.

Source: the sqlite-first install change. The plugin installer
(scripts/install-plugin.sh) persists the provisioned backend to
~/.claude/methodology/backend.json; scripts/launcher.py resolves it into
CORTEX_MEMORY_STORE_BACKEND at launch. The precedence contract under
test is the module docstring's five cases — in particular case 3, the
"never silently downgrade an existing PostgreSQL install" invariant.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mcp_server.infrastructure.backend_marker import (
    apply_backend_resolution,
    effective_backend,
    read_backend_marker,
    resolve_backend_env,
)


def _marker(tmp_path: Path, payload) -> Path:
    path = tmp_path / "backend.json"
    path.write_text(
        payload if isinstance(payload, str) else json.dumps(payload),
        encoding="utf-8",
    )
    return path


# ── read_backend_marker ─────────────────────────────────────────────────


class TestReadBackendMarker:
    def test_missing_file_returns_none(self, tmp_path):
        assert read_backend_marker(tmp_path / "absent.json") is None

    def test_invalid_json_returns_none(self, tmp_path):
        assert read_backend_marker(_marker(tmp_path, "{not json")) is None

    def test_non_dict_returns_none(self, tmp_path):
        assert read_backend_marker(_marker(tmp_path, ["sqlite"])) is None

    def test_unknown_backend_returns_none(self, tmp_path):
        assert read_backend_marker(_marker(tmp_path, {"backend": "mongodb"})) is None

    @pytest.mark.parametrize("backend", ["sqlite", "postgresql"])
    def test_valid_marker_returned(self, tmp_path, backend):
        marker = read_backend_marker(_marker(tmp_path, {"backend": backend}))
        assert marker is not None
        assert marker["backend"] == backend


# ── resolve_backend_env — precedence chain ──────────────────────────────


class TestResolveBackendEnv:
    def test_explicit_store_backend_wins_over_marker(self):
        env = {"CORTEX_MEMORY_STORE_BACKEND": "postgresql"}
        assert resolve_backend_env(env, {"backend": "sqlite"}) == {}

    @pytest.mark.parametrize(
        "requested,expected",
        [
            ("postgres", "postgresql"),
            ("postgresql", "postgresql"),
            ("POSTGRES", "postgresql"),  # case-insensitive
            ("sqlite", "sqlite"),
        ],
    )
    def test_cortex_backend_alias_mapping(self, requested, expected):
        env = {"CORTEX_BACKEND": requested}
        assert resolve_backend_env(env, None) == {
            "CORTEX_MEMORY_STORE_BACKEND": expected
        }

    def test_cortex_backend_beats_marker(self):
        env = {"CORTEX_BACKEND": "postgres"}
        assert resolve_backend_env(env, {"backend": "sqlite"}) == {
            "CORTEX_MEMORY_STORE_BACKEND": "postgresql"
        }

    def test_database_url_protects_existing_postgres(self):
        """Case 3: an operator URL means the marker must NOT downgrade."""
        env = {"DATABASE_URL": "postgresql://db.example:5432/cortex"}
        assert resolve_backend_env(env, {"backend": "sqlite"}) == {}

    def test_prefixed_database_url_also_protects(self):
        env = {"CORTEX_MEMORY_DATABASE_URL": "postgresql://db.example:5432/cortex"}
        assert resolve_backend_env(env, {"backend": "sqlite"}) == {}

    def test_blank_database_url_means_not_configured(self):
        """plugin.json interpolates an empty user_config default."""
        env = {"DATABASE_URL": "   "}
        assert resolve_backend_env(env, {"backend": "sqlite"}) == {
            "CORTEX_MEMORY_STORE_BACKEND": "sqlite"
        }

    @pytest.mark.parametrize("backend", ["sqlite", "postgresql"])
    def test_marker_applies_when_nothing_configured(self, backend):
        assert resolve_backend_env({}, {"backend": backend}) == {
            "CORTEX_MEMORY_STORE_BACKEND": backend
        }

    def test_no_marker_no_config_is_noop(self):
        assert resolve_backend_env({}, None) == {}

    def test_never_mutates_input(self):
        env = {"CORTEX_BACKEND": "sqlite"}
        resolve_backend_env(env, None)
        assert env == {"CORTEX_BACKEND": "sqlite"}


# ── apply_backend_resolution ────────────────────────────────────────────


class TestApplyBackendResolution:
    def test_applies_marker_to_environ(self, tmp_path):
        path = _marker(tmp_path, {"backend": "sqlite"})
        env: dict[str, str] = {}
        additions = apply_backend_resolution(env, marker_path=path)
        assert additions == {"CORTEX_MEMORY_STORE_BACKEND": "sqlite"}
        assert env["CORTEX_MEMORY_STORE_BACKEND"] == "sqlite"

    def test_strips_blank_database_url(self, tmp_path):
        path = _marker(tmp_path, {"backend": "sqlite"})
        env = {"DATABASE_URL": ""}
        apply_backend_resolution(env, marker_path=path)
        assert "DATABASE_URL" not in env
        assert env["CORTEX_MEMORY_STORE_BACKEND"] == "sqlite"

    def test_keeps_real_database_url_and_backend_untouched(self, tmp_path):
        path = _marker(tmp_path, {"backend": "sqlite"})
        env = {"DATABASE_URL": "postgresql://db.example:5432/cortex"}
        additions = apply_backend_resolution(env, marker_path=path)
        assert additions == {}
        assert env == {"DATABASE_URL": "postgresql://db.example:5432/cortex"}


# ── effective_backend ───────────────────────────────────────────────────


class TestEffectiveBackend:
    def test_env_var_short_circuits(self, tmp_path):
        path = _marker(tmp_path, {"backend": "postgresql"})
        env = {"CORTEX_MEMORY_STORE_BACKEND": "sqlite"}
        assert effective_backend(env, marker_path=path) == "sqlite"

    def test_auto_env_var_resolves_to_engine_default(self, tmp_path):
        path = _marker(tmp_path, {"backend": "sqlite"})
        env = {"CORTEX_MEMORY_STORE_BACKEND": "auto"}
        assert effective_backend(env, marker_path=path) == ""

    def test_marker_resolves_without_mutation(self, tmp_path):
        path = _marker(tmp_path, {"backend": "sqlite"})
        env: dict[str, str] = {}
        assert effective_backend(env, marker_path=path) == "sqlite"
        assert env == {}

    def test_unconfigured_is_empty(self, tmp_path):
        assert effective_backend({}, marker_path=tmp_path / "absent.json") == ""
