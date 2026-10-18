"""Regression: a caller-supplied ``domain`` must not escape the wiki root.

``record_session_end`` passed an explicit ``domain`` verbatim to the ADR
task record writer, which joined it into ``adr/<domain>/<file>.md`` under
the wiki root with no containment check.
"""

from __future__ import annotations

import pytest

from mcp_server.handlers import auto_task_record_writer as writer
from mcp_server.handlers.record_session_end import _resolve_domain

_TRAVERSAL = "../../../escaped-domain"


@pytest.fixture
def wiki(tmp_path, monkeypatch):
    root = tmp_path / "a" / "b" / "wiki"
    root.mkdir(parents=True)
    monkeypatch.setattr(writer, "WIKI_ROOT", root)
    monkeypatch.setattr(
        writer,
        "_git_commits_in_window",
        lambda cwd, minutes: [
            {"hash": "abc", "message": "add a", "files": ["a.txt"], "timestamp": "t"}
        ],
    )
    return root


def _write(domain: str) -> dict:
    return writer.maybe_write_task_record(
        session_id="s1",
        domain=domain,
        cwd=None,
        duration_seconds=60.0,
        turn_count=1,
        tools_used=[],
        store=None,
    )


def test_writer_refuses_path_outside_wiki_root(wiki, tmp_path):
    result = _write(_TRAVERSAL)

    assert result["status"] == "error"
    assert not list(tmp_path.rglob("escaped-domain"))


def test_writer_still_writes_inside_wiki_root(wiki):
    result = _write("my-project")

    assert result["status"] == "written"
    assert (wiki / result["path"]).is_file()


def test_resolve_domain_sanitizes_explicit_domain():
    resolved = _resolve_domain(_TRAVERSAL, None, None, {})

    assert "/" not in resolved and ".." not in resolved
    assert _resolve_domain("my-project", None, None, {}) == "my-project"


def test_writer_refuses_symlinked_domain_dir_outside_wiki_root(wiki, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (wiki / "adr").mkdir()
    (wiki / "adr" / "linked").symlink_to(outside, target_is_directory=True)

    result = _write("linked")

    assert result["status"] == "error"
    assert not list(outside.iterdir())


@pytest.mark.parametrize(
    "raw",
    [
        "/etc/escaped-domain",
        "..\\..\\..\\escaped-domain",
        "..%2f..%2f..%2fescaped-domain",
        "./../escaped-domain",
        "escaped\x00domain",
    ],
    ids=["absolute", "backslash", "percent-encoded", "dot-slash", "nul-byte"],
)
def test_resolve_domain_sanitizes_path_like_variants(raw):
    resolved = _resolve_domain(raw, None, None, {})

    assert resolved
    assert not any(ch in resolved for ch in ("/", "\\", "\x00", "%"))
    assert ".." not in resolved
