"""scripts/launcher_deps.py: the uv.lock-keyed stamp and the set each path installs.

source: ADR-1092"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DEPS_MODULE_PATH = REPO_ROOT / "scripts" / "launcher_deps.py"
DIGEST = "d" * 64


@pytest.fixture
def deps_mod():
    # Dotted name mutmut derives from the file location (issue #262).
    spec = importlib.util.spec_from_file_location(
        "scripts.launcher_deps", DEPS_MODULE_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def deps_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "deps"
    directory.mkdir()
    return directory


@pytest.fixture
def calls(deps_mod, monkeypatch) -> list[tuple[str, tuple[str, ...]]]:
    """Record every locked-set install; each one succeeds and imports."""
    seen: list[tuple[str, tuple[str, ...]]] = []

    def fake_install(deps_dir_arg, set_args):
        seen.append((deps_dir_arg, tuple(set_args)))
        return True

    monkeypatch.setattr(deps_mod, "lock_digest", lambda: DIGEST)
    monkeypatch.setattr(deps_mod, "_install_locked_set", fake_install)
    monkeypatch.setattr(deps_mod, "_importable", lambda *_a: True)
    return seen


def _stamp(deps_mod, deps_dir: Path, kind: str) -> dict:
    return json.loads(Path(deps_mod._stamp_path(str(deps_dir), kind)).read_text())


def test_lock_digest_is_the_sha256_of_the_repository_uv_lock(deps_mod):
    expected = hashlib.sha256((REPO_ROOT / "uv.lock").read_bytes()).hexdigest()
    assert deps_mod.LOCK_PATH == REPO_ROOT / "uv.lock"
    assert deps_mod.lock_digest() == expected


def test_lock_digest_is_none_without_a_lock(deps_mod, tmp_path, monkeypatch):
    monkeypatch.setattr(deps_mod, "LOCK_PATH", tmp_path / "absent.lock")
    assert deps_mod.lock_digest() is None


def test_stamp_round_trip_and_exact_payload(deps_mod, deps_dir):
    assert deps_mod._stamp_matches(str(deps_dir), "base", DIGEST) is False
    deps_mod._write_stamp(str(deps_dir), "base", DIGEST)
    assert deps_mod._stamp_matches(str(deps_dir), "base", DIGEST) is True
    assert _stamp(deps_mod, deps_dir, "base") == {
        "python": f"{sys.version_info.major}.{sys.version_info.minor}",
        "lock": DIGEST,
    }


def test_stamp_misses_on_another_lock_python_or_corrupt_file(deps_mod, deps_dir):
    deps_mod._write_stamp(str(deps_dir), "base", DIGEST)
    assert deps_mod._stamp_matches(str(deps_dir), "base", "e" * 64) is False
    assert deps_mod._stamp_matches(str(deps_dir), "ml", DIGEST) is False
    path = Path(deps_mod._stamp_path(str(deps_dir), "base"))
    path.write_text(json.dumps({"python": "0.0", "lock": DIGEST}))
    assert deps_mod._stamp_matches(str(deps_dir), "base", DIGEST) is False
    path.write_text("not json{")
    assert deps_mod._stamp_matches(str(deps_dir), "base", DIGEST) is False


def test_write_stamp_swallows_an_unwritable_destination(deps_mod, tmp_path):
    missing = tmp_path / "does-not-exist" / "deps"
    deps_mod._write_stamp(str(missing), "base", DIGEST)
    assert not Path(deps_mod._stamp_path(str(missing), "base")).exists()


def test_ensure_deps_installs_the_base_set_then_stamps(deps_mod, deps_dir, calls):
    deps_mod.ensure_deps(str(deps_dir))
    assert calls == [(str(deps_dir), ("--only-group", "launcher-base"))]
    assert _stamp(deps_mod, deps_dir, "base")["lock"] == DIGEST
    stamps = {p.name for p in deps_dir.iterdir() if p.name.startswith(".cortex")}
    assert stamps == {".cortex-deps-stamp-base.json"}


def test_ensure_deps_runs_nothing_when_the_stamp_matches(deps_mod, deps_dir, calls):
    deps_mod._write_stamp(str(deps_dir), "base", DIGEST)
    deps_mod.ensure_deps(str(deps_dir))
    assert calls == []


def test_fast_path_reads_the_stamp_of_this_kind_and_lock(
    deps_mod, deps_dir, calls, monkeypatch
):
    seen = []
    real = deps_mod._stamp_matches
    monkeypatch.setattr(
        deps_mod, "_stamp_matches", lambda *a: seen.append(a) or real(*a)
    )
    deps_mod._write_stamp(str(deps_dir), "base", DIGEST)
    deps_mod.ensure_deps(str(deps_dir))
    assert seen == [(str(deps_dir), "base", DIGEST)]


def test_ensure_deps_rechecks_the_stamp_under_the_lock(
    deps_mod, deps_dir, calls, monkeypatch
):
    """Another process finished while this one waited: no second install."""
    real_lock = deps_mod._deps_lock

    def lock_then_peer_stamps(path):
        assert path == str(deps_dir)
        deps_mod._write_stamp(str(deps_dir), "base", DIGEST)
        return real_lock(path)

    monkeypatch.setattr(deps_mod, "_deps_lock", lock_then_peer_stamps)
    deps_mod.ensure_deps(str(deps_dir))
    assert calls == []


def test_ensure_deps_holds_the_deps_dir_lock_while_installing(
    deps_mod, deps_dir, calls, monkeypatch
):
    held = []
    monkeypatch.setattr(
        deps_mod,
        "_install_locked_set",
        lambda d, _s: held.append(Path(f"{d}.lock").is_dir()) or True,
    )
    deps_mod.ensure_deps(str(deps_dir))
    assert held == [True]


def test_failed_install_or_import_never_stamps(deps_mod, deps_dir, calls, monkeypatch):
    monkeypatch.setattr(deps_mod, "_install_locked_set", lambda *_a: False)
    deps_mod.ensure_deps(str(deps_dir))
    assert not Path(deps_mod._stamp_path(str(deps_dir), "base")).exists()
    monkeypatch.setattr(deps_mod, "_install_locked_set", lambda *_a: True)
    monkeypatch.setattr(deps_mod, "_importable", lambda name, _d: name != "sqlite_vec")
    deps_mod.ensure_deps(str(deps_dir))
    assert not Path(deps_mod._stamp_path(str(deps_dir), "base")).exists()


def test_ensure_deps_checks_every_base_import_in_deps_dir(
    deps_mod, deps_dir, calls, monkeypatch
):
    checked = []
    monkeypatch.setattr(
        deps_mod, "_importable", lambda name, d: checked.append((name, d)) or True
    )
    deps_mod.ensure_deps(str(deps_dir))
    assert checked == [(name, str(deps_dir)) for name in deps_mod._sets.BASE_IMPORTS]


def test_missing_lock_installs_nothing_and_says_why(
    deps_mod, deps_dir, calls, monkeypatch, capsys
):
    monkeypatch.setattr(deps_mod, "lock_digest", lambda: None)
    deps_mod.ensure_all_deps(str(deps_dir))
    assert calls == []
    assert (
        capsys.readouterr().err
        == (
            f"[cortex-launcher] {deps_mod.LOCK_PATH} is missing; cannot install "
            "dependencies. Reinstall the plugin.\n"
        )
        * 2
    )


def test_ensure_all_deps_installs_base_then_ml(deps_mod, deps_dir, calls):
    deps_mod.ensure_all_deps(str(deps_dir))
    assert calls == [
        (str(deps_dir), ("--only-group", "launcher-base")),
        (str(deps_dir), ("--only-group", "launcher-ml")),
    ]
    assert _stamp(deps_mod, deps_dir, "ml")["lock"] == DIGEST
    names = {p.name for p in deps_dir.iterdir() if p.name.startswith(".cortex")}
    assert names == {".cortex-deps-stamp-base.json", ".cortex-deps-stamp-ml.json"}


def test_ensure_deps_sweeps_stale_backups_even_on_the_fast_path(
    deps_mod, deps_dir, calls, monkeypatch
):
    (deps_dir / "numpy.bak-4242").mkdir()
    deps_mod._write_stamp(str(deps_dir), "base", DIGEST)
    monkeypatch.setattr(deps_mod._fs, "pid_alive", lambda _pid: False)
    deps_mod.ensure_deps(str(deps_dir))
    assert not (deps_dir / "numpy.bak-4242").exists()


def test_installer_set_is_installed_under_the_lock(deps_mod, tmp_path, calls):
    deps_dir = tmp_path / "fresh" / "deps"
    assert deps_mod.main([str(deps_dir)]) == 0
    assert calls == [(str(deps_dir), deps_mod._sets.INSTALLER)]
    assert not Path(f"{deps_dir}.lock").exists()


def test_installer_set_sweeps_and_locks_its_own_deps_dir(
    deps_mod, deps_dir, calls, monkeypatch
):
    (deps_dir / "numpy.bak-4242").mkdir()
    monkeypatch.setattr(deps_mod._fs, "pid_alive", lambda _pid: False)
    held = []
    monkeypatch.setattr(
        deps_mod,
        "_install_locked_set",
        lambda d, _s: held.append(Path(f"{d}.lock").is_dir()) or True,
    )
    assert deps_mod.install_installer_set(str(deps_dir)) is True
    assert held == [True]
    assert not (deps_dir / "numpy.bak-4242").exists()


def test_installer_cli_help_is_the_function_docstring(deps_mod, capsys):
    with pytest.raises(SystemExit):
        deps_mod.main(["--help"])
    assert "Install the installers' set" in capsys.readouterr().out


def test_installer_cli_exits_nonzero_when_the_install_fails(
    deps_mod, deps_dir, monkeypatch
):
    monkeypatch.setattr(deps_mod, "_install_locked_set", lambda *_a: False)
    assert deps_mod.main([str(deps_dir)]) == 1
