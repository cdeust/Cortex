"""The CI-side no-deps gate: catches what the PreToolUse hook cannot see —
a file already committed, or written by a tool other than Claude Code.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_DIR = str(REPO_ROOT / "scripts")
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)
import check_no_deps_invariant as gate  # noqa: E402

BROKEN = (
    'python3 -m pip install -q --target "$DEPS_DIR" \\\n'
    '    --require-hashes -r "$PROJECT_DIR/requirements/setup.txt"\n'
)
FIXED = (
    'python3 -m pip install -q --target "$DEPS_DIR" \\\n'
    '    --no-deps --require-hashes -r "$PROJECT_DIR/requirements/setup.txt"\n'
)


def _write(tmp_path: Path, rel: str, body: str) -> Path:
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, "utf-8")
    return path


def test_scan_flags_the_broken_form(tmp_path: Path, monkeypatch) -> None:
    _write(tmp_path, "scripts/setup.sh", BROKEN)
    monkeypatch.setattr(gate, "REPO_ROOT", tmp_path)
    violations = gate.scan(["scripts/setup.sh"])
    assert len(violations) == 1
    assert violations[0][0] == "scripts/setup.sh"


def test_scan_passes_the_fixed_form(tmp_path: Path, monkeypatch) -> None:
    _write(tmp_path, "scripts/setup.sh", FIXED)
    monkeypatch.setattr(gate, "REPO_ROOT", tmp_path)
    assert gate.scan(["scripts/setup.sh"]) == []


def test_scan_ignores_out_of_scope_files(tmp_path: Path, monkeypatch) -> None:
    _write(tmp_path, "docs/example.sh", BROKEN)
    monkeypatch.setattr(gate, "REPO_ROOT", tmp_path)
    assert gate.scan(["docs/example.sh"]) == []


def test_scan_survives_a_missing_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(gate, "REPO_ROOT", tmp_path)
    assert gate.scan(["scripts/does_not_exist.sh"]) == []


def test_the_actual_tracked_repo_is_clean() -> None:
    """The invariant this gate exists to hold: run it for real, against the
    checked-out tree, the way CI will.

    Skipped rather than failed when ``git ls-files`` finds nothing: mutation
    testing runs this module from a copied, non-git working tree
    (``mutants/``), where an empty result is a property of that copy, not
    of the invariant this test protects.
    """
    files = gate.tracked_files()
    if not files:
        pytest.skip("not running against a git checkout (git ls-files found nothing)")
    assert gate.scan(files) == []


def test_tracked_files_parses_null_separated_git_output(monkeypatch) -> None:
    """Unit-level coverage for the parsing itself, independent of whether
    the test process happens to be inside a git checkout."""

    class _Result:
        stdout = b"scripts/a.sh\0.github/workflows/b.yml\0"

    monkeypatch.setattr(
        gate.subprocess, "run", lambda *a, **k: _Result(), raising=False
    )
    assert gate.tracked_files() == ["scripts/a.sh", ".github/workflows/b.yml"]


def test_tracked_files_returns_none_when_git_fails(monkeypatch) -> None:
    def _raise(*a, **k):
        raise subprocess.CalledProcessError(1, "git")

    monkeypatch.setattr(gate.subprocess, "run", _raise, raising=False)
    assert gate.tracked_files() is None


def test_entrypoint_exits_one_on_a_violation(tmp_path: Path) -> None:
    _write(tmp_path, "scripts/setup.sh", BROKEN)
    done = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "check_no_deps_invariant.py"),
            str(tmp_path / "scripts" / "setup.sh"),
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert done.returncode == 1
    assert "no-deps-invariant" in done.stderr


def test_main_exits_two_when_git_cannot_enumerate(monkeypatch) -> None:
    monkeypatch.setattr(gate, "tracked_files", lambda: None)
    assert gate.main([]) == 2


def test_entrypoint_exits_zero_on_the_fixed_form(tmp_path: Path) -> None:
    _write(tmp_path, "scripts/setup.sh", FIXED)
    done = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "check_no_deps_invariant.py"),
            str(tmp_path / "scripts" / "setup.sh"),
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert done.returncode == 0
