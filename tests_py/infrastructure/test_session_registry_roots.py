"""Project roots of the live windows (issue #711, slice 3a).

``write_session`` records the window's project root; ``live_project_roots``
reads the roots of the live windows back for the code-graph cache eviction,
and answers None (unknown) whenever a live window has no recorded root.
"""

from __future__ import annotations

import json

import pytest

import mcp_server.infrastructure.session_registry as sr
import mcp_server.infrastructure.session_registry_roots as roots


@pytest.fixture
def registry(tmp_path, monkeypatch):
    target = tmp_path / "session-registry"
    monkeypatch.setattr(sr, "registry_dir", lambda: target)
    monkeypatch.setattr(sr, "_process_start_signature", lambda pid: f"sig-{pid}")
    monkeypatch.setattr(roots, "pid_alive", lambda pid: pid != 666)
    return target


def _entry(d, pid: int, **fields) -> None:
    d.mkdir(parents=True, exist_ok=True)
    data = {"v": 1, "session_id": "s", "claude_pid": pid}
    data["claude_start_time"] = f"sig-{pid}"
    data.update(fields)
    (d / f"{pid}.json").write_text(json.dumps(data), encoding="utf-8")


def test_write_session_records_the_resolved_root(registry, tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    alias = tmp_path / "proj" / ".." / "proj"

    assert sr.write_session("s", claude_pid=41, project_root=str(alias)) is True

    data = json.loads((registry / "41.json").read_text(encoding="utf-8"))
    assert data["project_root"] == str(project.resolve())


def test_write_session_without_root_records_none(registry):
    assert sr.write_session("s", claude_pid=42) is True
    data = json.loads((registry / "42.json").read_text(encoding="utf-8"))
    assert data["project_root"] is None


def test_written_entries_read_back_as_live_roots(registry, tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    sr.write_session("s1", claude_pid=11, project_root=str(a))
    sr.write_session("s2", claude_pid=12, project_root=str(b))

    assert roots.live_project_roots() == {str(a.resolve()), str(b.resolve())}


def test_missing_registry_means_no_live_window(registry):
    assert roots.live_project_roots() == frozenset()


def test_unreadable_registry_is_unknown(monkeypatch, tmp_path):
    not_a_dir = tmp_path / "file"
    not_a_dir.write_text("x", encoding="utf-8")
    monkeypatch.setattr(sr, "registry_dir", lambda: not_a_dir)
    assert roots.live_project_roots() is None


def test_live_window_without_root_makes_the_set_unknown(registry):
    _entry(registry, 21, project_root="/p")
    _entry(registry, 22)  # written before slice 3a: no project_root key
    assert roots.live_project_roots() is None


@pytest.mark.parametrize("bad_root", ["", 42])
def test_live_window_with_an_empty_or_non_text_root_is_unknown(registry, bad_root):
    _entry(registry, 24, project_root=bad_root)
    assert roots.live_project_roots() is None


def test_tombstoned_live_window_is_unknown(registry):
    """A tombstone keeps the window alive but records no root."""
    sr.tombstone(23)
    assert roots.live_project_roots() is None


@pytest.mark.parametrize(
    ("pid", "fields"),
    [
        (666, {"project_root": "/dead"}),  # pid not alive
        (31, {"project_root": "/recycled", "claude_start_time": "other"}),
        (32, {"project_root": "/old", "v": 99}),
        (33, {"project_root": "/mismatch", "claude_pid": 34}),
    ],
)
def test_entries_that_are_not_live_windows_are_skipped(registry, pid, fields):
    _entry(registry, pid, **fields)
    _entry(registry, 40, project_root="/live")
    assert roots.live_project_roots() == {"/live"}


def test_non_registry_files_are_skipped(registry):
    _entry(registry, 50, project_root="/live")
    (registry / "notes.txt").write_text("x", encoding="utf-8")
    (registry / "abc.json").write_text("{}", encoding="utf-8")
    (registry / "51.json").write_text("not json", encoding="utf-8")
    assert roots.live_project_roots() == {"/live"}
