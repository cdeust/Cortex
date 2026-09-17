"""Worktree parser and consumer contracts. Source: ADR-1079."""

import asyncio

import pytest

from mcp_server import doctor
from mcp_server.handlers import check_setup


@pytest.mark.parametrize("output", [None, "", "HEAD abc\0\0"])
def test_unavailable_or_empty_listing_contract(monkeypatch, output):
    # This test runs inside the real repository checkout, so the `.git`
    # probe in `_worktree_locations` passes and a mocked `None` here
    # exercises the "Git unavailable or command failed" WARN, not the
    # "not a git checkout" pass — that case is covered separately by
    # test_not_a_git_checkout_passes / test_git_unavailable_in_a_checkout_warns
    # in tests_py/test_doctor.py.
    monkeypatch.setattr(doctor, "run_with_hard_timeout", lambda *a, **k: output)
    check = doctor._worktree_locations()
    assert check.optional
    if output is None:
        assert doctor._worktree_list() is None
        assert check.ok is False
        assert "Unable to inspect worktree locations" in check.detail
        assert "Git unavailable or command failed" in check.detail
        assert "git worktree list --porcelain -z" in check.fix
    else:
        assert doctor._worktree_list() == []
        assert check.ok
        assert check.detail == "no registered worktrees"
        assert check.fix == ""


def test_nul_parser_preserves_records_markers_and_unicode(monkeypatch, tmp_path):
    main = str(tmp_path / "répo")
    linked = str(tmp_path / "deleted")
    output = f"worktree {main}\0bare\0\0worktree {linked}\0prunable gone\0\0"
    calls = []

    def execute(argv, **kwargs):
        calls.append(argv)
        return output

    monkeypatch.setattr(doctor, "run_with_hard_timeout", execute)
    assert doctor._worktree_list() == [
        {"path": main, "bare": True, "prunable": False},
        {"path": linked, "bare": False, "prunable": True},
    ]
    assert calls == [["git", "worktree", "list", "--porcelain", "-z"]]


def test_orphan_markers_are_ignored(monkeypatch, tmp_path):
    output = f"bare\0prunable gone\0worktree {tmp_path}\0HEAD abc\0\0"
    monkeypatch.setattr(doctor, "run_with_hard_timeout", lambda *a, **k: output)
    assert doctor._worktree_list() == [
        {"path": str(tmp_path), "bare": False, "prunable": False}
    ]


@pytest.mark.parametrize("outside", [False, True])
def test_real_worktree_check_cli_and_mcp_contract(
    monkeypatch, tmp_path, capsys, outside
):
    location = tmp_path / ("outside" if outside else ".Codex/worktrees/good")
    entries = [{"path": str(tmp_path)}, {"path": str(location)}]
    monkeypatch.setattr(doctor, "_worktree_list", lambda: entries)
    monkeypatch.setattr(doctor, "active_checks", lambda: [doctor._worktree_locations])
    monkeypatch.setattr(
        check_setup, "active_checks", lambda: [doctor._worktree_locations]
    )
    monkeypatch.setattr(doctor.sys, "argv", ["doctor"])
    assert doctor.run() == 0
    output = capsys.readouterr().out
    check = doctor._worktree_locations()
    assert check.ok is not outside
    assert ("[WARN]" in output) is outside
    assert "[FAIL]" not in output
    if outside:
        assert str(location.resolve()) in output
        assert check.fix in output
        assert ".Codex/worktrees/<name>/" in check.fix
        assert ".claude/worktrees/<name>/" in check.fix
    else:
        assert check.fix == ""
        assert "All checks passed" in output
    result = asyncio.run(check_setup.handler())
    assert result["ready"] is True and result["fixes_needed"] == 0
    assert result["checks"] == [
        {
            "name": check.name,
            "ok": check.ok,
            "optional": True,
            "detail": check.detail,
            "fix_command": check.fix,
        }
    ]


def test_registries_include_optional_worktree_check():
    assert doctor._worktree_locations in doctor.CHECKS
    assert doctor._worktree_locations in doctor.SQLITE_CHECKS


def test_bare_and_exact_root_details(tmp_path):
    ok, detail = doctor._worktree_classification(
        [{"path": str(tmp_path), "bare": True}]
    )
    assert ok and detail == "bare repository — rule not applicable"
    root = (tmp_path / ".Codex/worktrees").resolve()
    assert doctor._under(root, root)
    ok, detail = doctor._worktree_classification(
        [
            {"path": str(tmp_path)},
            {"path": str(root)},
            {"path": str(root)},
        ]
    )
    assert ok and str(root) in detail
    assert str((tmp_path / ".claude/worktrees").resolve()) in detail


def test_unavailable_listing_warns_without_blocking_consumers(monkeypatch, capsys):
    monkeypatch.setattr(doctor, "run_with_hard_timeout", lambda *a, **k: None)
    monkeypatch.setattr(doctor, "active_checks", lambda: [doctor._worktree_locations])
    monkeypatch.setattr(
        check_setup, "active_checks", lambda: [doctor._worktree_locations]
    )
    monkeypatch.setattr(doctor.sys, "argv", ["doctor"])
    assert doctor.run() == 0
    output = capsys.readouterr().out
    assert "[WARN]" in output and "[FAIL]" not in output
    assert "Unable to inspect worktree locations" in output
    assert "git worktree list --porcelain -z" in output
    result = asyncio.run(check_setup.handler())
    assert result["ready"] and result["fixes_needed"] == 0
    check = result["checks"][0]
    assert check["optional"] and not check["ok"]
    assert "Unable to inspect worktree locations" in check["detail"]
    assert "git worktree list --porcelain -z" in check["fix_command"]
