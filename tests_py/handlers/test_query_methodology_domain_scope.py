"""query_methodology reads hot memories under the scope remember writes (#721).

``detect_domain`` returns a cognitive-profile id. ``query_methodology`` handed
that id to ``get_memories_for_domain``, while ``remember`` without an explicit
domain writes under ``resolve_cwd(cwd)`` and, outside a known repository,
under the detected profile resolved as a hint. When the profile id and the
written scope differ, session start listed the hot memories of a scope no
write used. Each test rebuilds the repository registry from real directories
under ``tmp_path``, runs the public handler, and reads the domain it hands to
the store.

source: issue #721; ADR-0647"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest

from mcp_server.handlers import query_methodology as methodology
from mcp_server.handlers import remember
from mcp_server.shared import domain_mapping as dm


class _FakeStore:
    """Records which scope it is asked for and holds no memory."""

    def __init__(self) -> None:
        self.domains: list[str] = []

    def get_memories_for_domain(self, domain, **_kwargs):
        self.domains.append(domain)
        return []

    def get_memories_for_directory(self, _directory, **_kwargs):
        return []

    def get_hot_memories(self, **_kwargs):
        return []


def _make_repo(dev_root: Path, name: str) -> Path:
    git_dir = dev_root / name / ".git"
    git_dir.mkdir(parents=True)
    (git_dir / "config").write_text(
        f'[remote "origin"]\n\turl = https://github.com/org/{name}.git\n'
    )
    return dev_root / name


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    dev_root = tmp_path / "dev"
    for name in ("cortex", "cortex-cowork", "harness-comparison"):
        _make_repo(dev_root, name)
    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.setattr(dm, "_candidate_dev_roots", lambda: [dev_root])
    dm._build_registry.cache_clear()
    yield {"repo": str(dev_root / "cortex"), "outside": str(outside)}
    dm._build_registry.cache_clear()


def _read_scope(cwd: str, profile_domain: str) -> str:
    store = _FakeStore()
    with patch.multiple(
        methodology,
        load_profiles=lambda: {"domains": {}},
        detect_domain=lambda *_a, **_k: {"domain": profile_domain},
        _try_get_memory_store=lambda: store,
        _get_fired_triggers=lambda *_a: [],
    ):
        with patch("mcp_server.core.telemetry.record"):
            asyncio.run(methodology.handler({"cwd": cwd}))
    return store.domains[-1] if store.domains else ""


def _write_scope(monkeypatch, cwd: str, profile_domain: str) -> str:
    monkeypatch.setattr(remember, "load_profiles", lambda: {"domains": {}})
    monkeypatch.setattr(
        remember, "detect_domain", lambda *_a, **_k: {"domain": profile_domain}
    )
    return remember._resolve_domain(cwd, "")


def test_known_repository_is_read_under_its_canonical(dirs):
    assert _read_scope(dirs["repo"], "legacy-profile-id") == "cortex"


def test_profile_outside_a_repository_is_read_as_remember_resolves_it(dirs):
    assert _read_scope(dirs["outside"], "cortex-cowork") == "cortex"


def test_profile_without_cwd_is_read_as_a_hint(dirs):
    assert _read_scope("", "cortex-cowork") == "cortex"


@pytest.mark.parametrize("where", ["repo", "outside"])
def test_no_profile_reads_the_repository_or_no_domain(dirs, where):
    expected = "cortex" if where == "repo" else ""
    assert _read_scope(dirs[where], "") == expected


@pytest.mark.parametrize(
    ("where", "profile_domain"),
    [
        ("repo", "legacy-profile-id"),
        ("repo", "cortex"),
        ("outside", "cortex-cowork"),
        ("outside", "SciFact-Comparison"),
    ],
)
def test_read_scope_equals_remember_write_scope(
    dirs, monkeypatch, where, profile_domain
):
    cwd = dirs[where]
    read = _read_scope(cwd, profile_domain)
    assert read == _write_scope(monkeypatch, cwd, profile_domain)
