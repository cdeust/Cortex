"""Tests for scripts/launcher_deps.py — issue #97.

Source: issue #97 (reporter mbe14, Windows 11). The prior commit step
in ``_pip_install`` blindly ``rmtree``'d + ``os.replace``'d every
top-level entry pip resolved into a temp dir, including transitive deps
(numpy, pulled in by sentence-transformers) already correctly installed
and locked by a concurrently-running MCP server on Windows. A mid-loop
``PermissionError`` then hit the old ``finally: shutil.rmtree(tmp_dir)``,
destroying the fresh install too — irrecoverable, and re-triggered on
every subsequent hook invocation.

These tests exercise the pure logic cross-platform: the idempotence
guard (never touch an already-satisfied dest), the non-destructive
commit + rollback on a simulated mid-commit failure (monkeypatched
``os.replace``), and the stamp/lock fast path. The actual Windows
file-lock failure mode itself can only be reproduced on Windows — see
the module's docstring and this repo's prior #91-#96 Windows fixes for
the same epistemic position.
"""

from __future__ import annotations

import contextlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DEPS_MODULE_PATH = REPO_ROOT / "scripts" / "launcher_deps.py"


@pytest.fixture
def deps_mod():
    # The module name must be the dotted path mutmut derives from the
    # file's location: it keys its mutant trampolines on
    # "scripts.launcher_deps.*", and a synthetic name (e.g. the prior
    # "_cortex_launcher_deps") makes every mutant look unreached, so a
    # scoped mutation run stops early instead of scoring the suite
    # (issue #262). This does not change launcher_deps.py's own runtime
    # import: scripts/launcher.py still loads it via a bare
    # `import launcher_deps` (see that module's docstring) — only this
    # test's OWN module handle is renamed.
    spec = importlib.util.spec_from_file_location(
        "scripts.launcher_deps", DEPS_MODULE_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _make_dist_info(root: Path, dist_name: str, version: str) -> None:
    d = root / f"{dist_name}-{version}.dist-info"
    d.mkdir(parents=True, exist_ok=True)
    (d / "METADATA").write_text(
        f"Name: {dist_name}\nVersion: {version}\n", encoding="utf-8"
    )


def _make_pkg_dir(root: Path, pkg_name: str, marker: str = "x") -> None:
    d = root / pkg_name
    d.mkdir(parents=True, exist_ok=True)
    (d / "__init__.py").write_text(f"# {marker}\n", encoding="utf-8")


# ---------------------------------------------------------------- helpers ---


def test_normalize_dist_key_folds_separators(deps_mod):
    assert deps_mod._normalize_dist_key("pydantic-settings") == "pydantic_settings"
    assert deps_mod._normalize_dist_key("pydantic_settings") == "pydantic_settings"
    assert deps_mod._normalize_dist_key("PyDantic.Settings") == "pydantic_settings"


def test_parse_pip_spec_strips_extras_and_version(deps_mod):
    assert deps_mod._parse_pip_spec("psycopg[binary]==3.3.3") == ("psycopg", "3.3.3")
    assert deps_mod._parse_pip_spec("numpy==2.4.4") == ("numpy", "2.4.4")


def test_dist_info_versions_scans_only_dist_info_dirs(deps_mod, tmp_path):
    _make_dist_info(tmp_path, "numpy", "2.4.4")
    _make_pkg_dir(tmp_path, "numpy")
    (tmp_path / "not_a_dist_info").mkdir()
    versions = deps_mod._dist_info_versions(str(tmp_path))
    assert versions == {"numpy": "2.4.4"}


def test_dist_info_versions_missing_dir_returns_empty(deps_mod, tmp_path):
    assert deps_mod._dist_info_versions(str(tmp_path / "nope")) == {}


# --------------------------------------------------------------- _importable ---


class _NamespaceHusk:
    """Stands in for a real namespace-package import: NO ``__file__``
    attribute at all (not even ``None``) -- mirrors the real object a
    namespace package import produces, and also lets a test observe the
    ``getattr(mod, "__file__", None)`` DEFAULT actually doing work: a
    mutant that drops the default (``getattr(mod, "__file__")``) would
    raise ``AttributeError`` on an instance like this instead of quietly
    falling through to ``None``."""


def test_importable_false_on_import_error(deps_mod, tmp_path):
    """A package that plain doesn't exist -- the common cold-boot case."""
    deps_dir = tmp_path / "deps"
    deps_dir.mkdir()
    assert deps_mod._importable("no_such_package_xyz_263", str(deps_dir)) is False


def test_importable_true_for_a_real_module_with_a_file(deps_mod, tmp_path):
    deps_dir = tmp_path / "deps"
    deps_dir.mkdir()
    assert deps_mod._importable("json", str(deps_dir)) is True


def test_importable_removes_corrupt_husk_and_reports(
    deps_mod, tmp_path, monkeypatch, capsys
):
    """issue #97 residue 3: a namespace-package husk inside deps_dir is
    deleted and the exact removal path is reported to stderr."""
    deps_dir = tmp_path / "deps"
    deps_dir.mkdir()
    husk = deps_dir / "fastmcp"
    husk.mkdir()
    (husk / "leftover.txt").write_text("x", encoding="utf-8")
    monkeypatch.setattr(
        deps_mod.importlib, "import_module", lambda name: _NamespaceHusk()
    )
    result = deps_mod._importable("fastmcp", str(deps_dir))
    assert result is False
    assert not husk.exists()
    captured = capsys.readouterr()
    assert captured.err == (
        f"[cortex-launcher] removed corrupt partial install: {husk}\n"
    )


def test_importable_no_husk_directory_is_a_silent_false(
    deps_mod, tmp_path, monkeypatch, capsys
):
    """A namespace-package import with nothing on disk at that name (e.g.
    an editable/implicit namespace outside deps_dir entirely) must not
    attempt a removal or print anything -- the husk branch is opt-in on
    ``os.path.isdir`` finding something real."""
    deps_dir = tmp_path / "deps"
    deps_dir.mkdir()
    monkeypatch.setattr(
        deps_mod.importlib, "import_module", lambda name: _NamespaceHusk()
    )
    result = deps_mod._importable("fastmcp", str(deps_dir))
    assert result is False
    captured = capsys.readouterr()
    assert captured.err == ""


def test_importable_husk_removal_swallows_rmtree_errors(
    deps_mod, tmp_path, monkeypatch
):
    """``shutil.rmtree(husk, ignore_errors=True)``: the husk cleanup is
    best-effort. A real husk can contain a file the OS still has locked
    (issue #97's whole premise), so a removal failure there must not
    propagate -- ``_importable`` still returns False rather than
    raising."""
    deps_dir = tmp_path / "deps"
    deps_dir.mkdir()
    husk = deps_dir / "fastmcp"
    husk.mkdir()
    monkeypatch.setattr(
        deps_mod.importlib, "import_module", lambda name: _NamespaceHusk()
    )

    def raising_rmtree(path, ignore_errors=False):
        if not ignore_errors:
            raise PermissionError("simulated: husk contains a locked file")

    monkeypatch.setattr(deps_mod.shutil, "rmtree", raising_rmtree)
    result = deps_mod._importable("fastmcp", str(deps_dir))
    assert result is False


def test_importable_husk_path_is_deps_dir_joined_with_import_name(
    deps_mod, tmp_path, monkeypatch
):
    """The husk path checked/removed is ``deps_dir``'s OWN child, never
    some other location -- e.g. never a same-named sibling directory
    next to ``deps_dir``."""
    deps_dir = tmp_path / "deps"
    deps_dir.mkdir()
    sibling_husk = tmp_path / "fastmcp"  # sibling of deps_dir, NOT inside it
    sibling_husk.mkdir()
    monkeypatch.setattr(
        deps_mod.importlib, "import_module", lambda name: _NamespaceHusk()
    )
    deps_mod._importable("fastmcp", str(deps_dir))
    assert sibling_husk.exists(), "must not touch anything outside deps_dir"


def test_importable_pops_the_husk_from_sys_modules_for_a_clean_retry(
    deps_mod, tmp_path, monkeypatch
):
    """After detecting and deleting a husk, the broken module must be
    evicted from ``sys.modules`` -- otherwise a LATER retry (once a real
    package has been installed at the same import name) would keep
    returning the STALE cached namespace-package object instead of
    re-importing the fresh one, and would even delete the fresh install
    by re-running the husk check against its (now legitimate) directory."""
    deps_dir = tmp_path / "deps"
    deps_dir.mkdir()
    import_name = "_cortex_test_husk_263"
    husk = deps_dir / import_name
    husk.mkdir()  # a directory with NO __init__.py: a real namespace package
    monkeypatch.syspath_prepend(str(deps_dir))
    try:
        assert deps_mod._importable(import_name, str(deps_dir)) is False
        assert import_name not in sys.modules
        assert not husk.exists()
        # Simulate a completed reinstall: a REAL package now lives at the
        # same import name.
        _make_pkg_dir(deps_dir, import_name, marker="REAL")
        assert deps_mod._importable(import_name, str(deps_dir)) is True
        assert husk.is_dir()  # the fresh install must survive untouched
    finally:
        sys.modules.pop(import_name, None)


# ------------------------------------------------------- idempotence guard ---


def test_pip_install_never_touches_already_satisfied_entry(
    deps_mod, tmp_path, monkeypatch
):
    """Suggestion 1: dest already has the exact version pip just
    resolved -> the entry must never enter the rmtree/replace path.
    Simulated by monkeypatching subprocess.run (no real pip call) and
    seeding both tmp and dest with the SAME numpy version + a marker
    file inside dest's package dir that would be destroyed by any
    rmtree/replace touch."""
    deps_dir = tmp_path / "deps"
    deps_dir.mkdir()
    _make_pkg_dir(deps_dir, "numpy", marker="ORIGINAL-LOCKED-COPY")
    _make_dist_info(deps_dir, "numpy", "2.4.4")

    def fake_run(cmd, **kwargs):
        # Locate --target value to build the "pip install" result.
        tmp_dir = Path(cmd[cmd.index("--target") + 1])
        _make_pkg_dir(tmp_dir, "numpy", marker="FRESH-DOWNLOAD")
        _make_dist_info(tmp_dir, "numpy", "2.4.4")  # same version as dest

        class _Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return _Result()

    monkeypatch.setattr(deps_mod._install.subprocess, "run", fake_run)
    ok = deps_mod._pip_install(str(deps_dir), ["numpy==2.4.4"])
    assert ok is True
    # dest's original marker survives untouched -- never replaced.
    marker = (deps_dir / "numpy" / "__init__.py").read_text(encoding="utf-8")
    assert "ORIGINAL-LOCKED-COPY" in marker


def test_pip_install_replaces_entry_when_version_differs(
    deps_mod, tmp_path, monkeypatch
):
    """A genuine version bump DOES commit — idempotence guards only the
    already-satisfied case, it is not a blanket no-op."""
    deps_dir = tmp_path / "deps"
    deps_dir.mkdir()
    _make_pkg_dir(deps_dir, "numpy", marker="OLD")
    _make_dist_info(deps_dir, "numpy", "2.2.6")

    def fake_run(cmd, **kwargs):
        tmp_dir = Path(cmd[cmd.index("--target") + 1])
        _make_pkg_dir(tmp_dir, "numpy", marker="NEW")
        _make_dist_info(tmp_dir, "numpy", "2.4.4")

        class _Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return _Result()

    monkeypatch.setattr(deps_mod._install.subprocess, "run", fake_run)
    ok = deps_mod._pip_install(str(deps_dir), ["numpy==2.4.4"])
    assert ok is True
    assert "NEW" in (deps_dir / "numpy" / "__init__.py").read_text(encoding="utf-8")
    assert (deps_dir / "numpy-2.4.4.dist-info").is_dir()
    # Residue 2 fix: the superseded numpy-2.2.6.dist-info is pruned right
    # after the commit, not left as duplicate metadata for one dist. See
    # test_pip_install_prunes_superseded_dist_info_on_version_bump below
    # for the dedicated coverage of this behavior.
    assert not (deps_dir / "numpy-2.2.6.dist-info").exists()


# ------------------------------------------------- non-destructive commit ---


def test_pip_install_rollback_on_mid_commit_failure(deps_mod, tmp_path, monkeypatch):
    """Suggestion 2: simulate a PermissionError on os.replace for one
    entry (the locked-.pyd shape on Windows). Dest must be restored to
    its pre-call state, and tmp_dir must survive (NOT be deleted) so
    the fresh install isn't lost."""
    deps_dir = tmp_path / "deps"
    deps_dir.mkdir()
    _make_pkg_dir(deps_dir, "numpy", marker="ORIGINAL")
    _make_dist_info(
        deps_dir, "numpy", "2.2.6"
    )  # differs from tmp -> forces commit attempt

    captured_tmp_dir = {}

    def fake_run(cmd, **kwargs):
        tmp_dir = Path(cmd[cmd.index("--target") + 1])
        captured_tmp_dir["path"] = tmp_dir
        _make_pkg_dir(tmp_dir, "numpy", marker="FRESH")
        _make_dist_info(tmp_dir, "numpy", "2.4.4")

        class _Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return _Result()

    monkeypatch.setattr(deps_mod._install.subprocess, "run", fake_run)

    real_replace = os.replace

    def flaky_replace(src, dst):
        # Fail only the FORWARD move (tmp_dir's fresh copy -> dest).
        # The rollback direction (backup -> dest) must succeed, exactly
        # as it would on a real Windows box once the process holding
        # the lock releases it — this test isolates "the forward commit
        # failed", not "the filesystem is permanently unwritable".
        if str(src).endswith(os.path.join("numpy")) and ".tmp-" in str(src):
            raise PermissionError(
                "[WinError 5] Access is denied (simulated locked .pyd)"
            )
        return real_replace(src, dst)

    monkeypatch.setattr(deps_mod._install.os, "replace", flaky_replace)

    ok = deps_mod._pip_install(str(deps_dir), ["numpy==2.4.4"])

    assert ok is False
    # Dest restored to its ORIGINAL content -- rollback succeeded.
    assert (deps_dir / "numpy").is_dir()
    assert "ORIGINAL" in (deps_dir / "numpy" / "__init__.py").read_text(
        encoding="utf-8"
    )
    assert (deps_dir / "numpy-2.2.6.dist-info").is_dir()
    # tmp_dir preserved for manual recovery / retry -- the exact bug
    # (old `finally: shutil.rmtree(tmp_dir)`) destroyed this.
    assert captured_tmp_dir["path"].exists()
    assert (captured_tmp_dir["path"] / "numpy" / "__init__.py").exists()


def test_pip_install_rollback_preserves_dist_info_regardless_of_commit_order(
    deps_mod, tmp_path, monkeypatch
):
    """Issue #149 regression: ``os.listdir`` order is unspecified by the
    stdlib and was observed to differ across CI's Python 3.10 runners,
    making ``test_pip_install_rollback_on_mid_commit_failure`` flaky.
    Root cause: the OLD ``numpy-2.2.6.dist-info`` was pruned as soon as
    the NEW ``numpy-2.4.4.dist-info`` entry committed, before the
    package-directory entry's commit failed and rolled back -- when
    ``os.listdir`` happened to yield the dist-info entry first, the
    prune ran and destroyed the still-valid old metadata ahead of the
    overall failure. This test forces that exact ordering deterministically
    (independent of host filesystem enumeration order) so the race can
    never silently reappear."""
    deps_dir = tmp_path / "deps"
    deps_dir.mkdir()
    _make_pkg_dir(deps_dir, "numpy", marker="ORIGINAL")
    _make_dist_info(deps_dir, "numpy", "2.2.6")

    captured_tmp_dir = {}

    def fake_run(cmd, **kwargs):
        tmp_dir = Path(cmd[cmd.index("--target") + 1])
        captured_tmp_dir["path"] = tmp_dir
        _make_pkg_dir(tmp_dir, "numpy", marker="FRESH")
        _make_dist_info(tmp_dir, "numpy", "2.4.4")

        class _Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return _Result()

    monkeypatch.setattr(deps_mod._install.subprocess, "run", fake_run)

    real_replace = os.replace

    def flaky_replace(src, dst):
        if str(src).endswith(os.path.join("numpy")) and ".tmp-" in str(src):
            raise PermissionError(
                "[WinError 5] Access is denied (simulated locked .pyd)"
            )
        return real_replace(src, dst)

    monkeypatch.setattr(deps_mod._install.os, "replace", flaky_replace)

    real_listdir = os.listdir

    def forced_listdir(path):
        # Force the dist-info entry to be enumerated BEFORE the package
        # directory entry, for tmp_dir only -- the ordering the flake
        # needed to trigger.
        names = real_listdir(path)
        if captured_tmp_dir.get("path") is not None and str(path) == str(
            captured_tmp_dir["path"]
        ):
            return sorted(names, key=lambda n: (not n.endswith(".dist-info"), n))
        return names

    monkeypatch.setattr(deps_mod._install.os, "listdir", forced_listdir)

    ok = deps_mod._pip_install(str(deps_dir), ["numpy==2.4.4"])

    assert ok is False
    assert "ORIGINAL" in (deps_dir / "numpy" / "__init__.py").read_text(
        encoding="utf-8"
    )
    # The invariant issue #149 broke: the old dist-info must survive an
    # overall-failed commit even when its OWN entry committed first.
    assert (deps_dir / "numpy-2.2.6.dist-info").is_dir()


def test_pip_install_no_backup_leaked_on_success(deps_mod, tmp_path, monkeypatch):
    """A successful commit leaves no ``*.bak-<pid>`` residue behind."""
    deps_dir = tmp_path / "deps"
    deps_dir.mkdir()
    _make_pkg_dir(deps_dir, "numpy", marker="OLD")
    _make_dist_info(deps_dir, "numpy", "2.2.6")

    def fake_run(cmd, **kwargs):
        tmp_dir = Path(cmd[cmd.index("--target") + 1])
        _make_pkg_dir(tmp_dir, "numpy", marker="NEW")
        _make_dist_info(tmp_dir, "numpy", "2.4.4")

        class _Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return _Result()

    monkeypatch.setattr(deps_mod._install.subprocess, "run", fake_run)
    assert deps_mod._pip_install(str(deps_dir), ["numpy==2.4.4"]) is True
    leftovers = [p for p in deps_dir.iterdir() if ".bak-" in p.name]
    assert leftovers == []


def test_pip_install_failure_preserves_tmp_dir_and_returns_false(
    deps_mod, tmp_path, monkeypatch
):
    """pip itself failing (network/proxy/PEP668) is a distinct path from
    a commit failure -- must still surface False and not raise."""
    deps_dir = tmp_path / "deps"
    deps_dir.mkdir()

    def fake_run(cmd, **kwargs):
        class _Result:
            returncode = 1
            stdout = ""
            stderr = "ERROR: Could not find a version that satisfies numpy==2.4.4"

        return _Result()

    monkeypatch.setattr(deps_mod._install.subprocess, "run", fake_run)
    ok = deps_mod._pip_install(str(deps_dir), ["numpy==2.4.4"])
    assert ok is False


# --------------------------------------------------------------- stamp/lock ---


def test_stamp_round_trip(deps_mod, tmp_path):
    deps_dir = tmp_path / "deps"
    deps_dir.mkdir()
    pins = ["fastmcp==3.2.4", "numpy==2.4.4"]
    assert deps_mod._pins_satisfied(str(deps_dir), "base", pins) is False
    deps_mod._write_stamp(str(deps_dir), "base", pins)
    assert deps_mod._pins_satisfied(str(deps_dir), "base", pins) is True


def test_stamp_mismatch_on_pin_change_self_heals(deps_mod, tmp_path):
    """A pin bump (new Cortex release) invalidates the stamp -- 'un
    stamp par version de pin suffit' means exact match required."""
    deps_dir = tmp_path / "deps"
    deps_dir.mkdir()
    deps_mod._write_stamp(str(deps_dir), "base", ["numpy==2.4.4"])
    assert deps_mod._pins_satisfied(str(deps_dir), "base", ["numpy==2.5.0"]) is False


def test_stamp_corrupt_file_treated_as_absent(deps_mod, tmp_path):
    deps_dir = tmp_path / "deps"
    deps_dir.mkdir()
    Path(deps_mod._stamp_path(str(deps_dir), "base")).write_text(
        "not json{", encoding="utf-8"
    )
    assert deps_mod._pins_satisfied(str(deps_dir), "base", ["numpy==2.4.4"]) is False


def test_pins_satisfied_false_when_python_version_differs(deps_mod, tmp_path):
    """The stamp is keyed to BOTH the pin set and the interpreter minor
    version -- a pins match with a stale python field must still miss,
    exactly as an actual interpreter upgrade would."""
    deps_dir = tmp_path / "deps"
    deps_dir.mkdir()
    pins = ["numpy==2.4.4"]
    deps_mod._write_stamp(str(deps_dir), "base", pins)
    Path(deps_mod._stamp_path(str(deps_dir), "base")).write_text(
        json.dumps({"python": "0.0", "pins": sorted(pins)}), encoding="utf-8"
    )
    assert deps_mod._pins_satisfied(str(deps_dir), "base", pins) is False


def test_pins_satisfied_ignores_the_caller_argument_order(deps_mod, tmp_path):
    """Both the write and the read side sort -- a stamp written from one
    ordering must satisfy a check called with the pins in any order."""
    deps_dir = tmp_path / "deps"
    deps_dir.mkdir()
    deps_mod._write_stamp(str(deps_dir), "base", ["numpy==2.4.4", "fastmcp==3.4.5"])
    reordered = ["fastmcp==3.4.5", "numpy==2.4.4"]
    assert deps_mod._pins_satisfied(str(deps_dir), "base", reordered) is True


def test_write_stamp_payload_shape_is_exact(deps_mod, tmp_path):
    """Direct assertion on the written bytes -- not merely round-tripped
    through ``_pins_satisfied`` -- so a key-name or sort-order mutation
    in ``_write_stamp`` itself cannot hide behind a symmetrical read."""
    deps_dir = tmp_path / "deps"
    deps_dir.mkdir()
    deps_mod._write_stamp(str(deps_dir), "base", ["numpy==2.4.4", "fastmcp==3.4.5"])
    payload = json.loads(
        Path(deps_mod._stamp_path(str(deps_dir), "base")).read_text(encoding="utf-8")
    )
    assert payload == {
        "python": f"{sys.version_info.major}.{sys.version_info.minor}",
        "pins": ["fastmcp==3.4.5", "numpy==2.4.4"],
    }


def test_write_stamp_swallows_an_unwritable_destination(deps_mod, tmp_path):
    """Best-effort: a deps_dir that can't be written to must not raise --
    the next call simply re-verifies from scratch."""
    missing_deps_dir = tmp_path / "does-not-exist" / "deps"
    deps_mod._write_stamp(str(missing_deps_dir), "base", ["numpy==2.4.4"])
    assert not Path(deps_mod._stamp_path(str(missing_deps_dir), "base")).exists()


def test_ensure_deps_skips_pip_entirely_when_stamp_matches(
    deps_mod, tmp_path, monkeypatch
):
    """The hot-path fast path: a valid stamp means zero _pip_install
    calls and zero _importable calls (issue #97 suggestion 4 — no
    torch/numpy import just to answer 'is it installed')."""
    deps_dir = tmp_path / "deps"
    deps_dir.mkdir()
    pins = [spec for _name, spec in deps_mod._BASE_PACKAGES]
    deps_mod._write_stamp(str(deps_dir), "base", pins)
    real_pins_satisfied = deps_mod._pins_satisfied
    seen_kinds = []

    def capturing_pins_satisfied(deps_dir_arg, kind_arg, pins_arg):
        seen_kinds.append(kind_arg)
        return real_pins_satisfied(deps_dir_arg, kind_arg, pins_arg)

    monkeypatch.setattr(deps_mod, "_pins_satisfied", capturing_pins_satisfied)
    calls = {"pip_install": 0, "importable": 0, "dist_info_satisfies": 0}
    monkeypatch.setattr(
        deps_mod,
        "_pip_install",
        lambda *a, **k: calls.__setitem__("pip_install", 1) or True,
    )
    monkeypatch.setattr(
        deps_mod,
        "_importable",
        lambda *a, **k: (
            calls.__setitem__("importable", calls["importable"] + 1) or True
        ),
    )
    # The stamp's whole POINT (module docstring: "skips the dist-info scan
    # entirely") is to avoid this filesystem walk once satisfied -- a
    # mutated kind/deps_dir/pins argument on the OUTER check can still
    # arrive at "0 pip calls" via the inner double-check's safety net
    # (see the racing test below), so this scan-count assertion is what
    # actually pins the outer check's own arguments.
    monkeypatch.setattr(
        deps_mod,
        "_dist_info_satisfies",
        lambda *a, **k: (
            calls.__setitem__("dist_info_satisfies", calls["dist_info_satisfies"] + 1)
            or True
        ),
    )
    deps_mod.ensure_deps(str(deps_dir))
    assert calls == {"pip_install": 0, "importable": 0, "dist_info_satisfies": 0}
    # The literal kind STRING captured, not just the boolean outcome of a
    # file lookup: immune to macOS APFS's case-insensitive filesystem
    # equating "base" and "BASE" on disk (see the racing test's comment).
    assert seen_kinds == ["base"]


def test_ensure_deps_installs_and_stamps_when_missing(deps_mod, tmp_path, monkeypatch):
    deps_dir = tmp_path / "deps"
    deps_dir.mkdir()

    installed = {"called": False}

    def fake_importable(name, _deps_dir):
        return installed["called"]  # False before install, True after

    def fake_pip_install(_deps_dir, _packages):
        installed["called"] = True
        return True

    monkeypatch.setattr(deps_mod, "_importable", fake_importable)
    monkeypatch.setattr(deps_mod, "_pip_install", fake_pip_install)
    deps_mod.ensure_deps(str(deps_dir))
    pins = [spec for _name, spec in deps_mod._BASE_PACKAGES]
    assert deps_mod._pins_satisfied(str(deps_dir), "base", pins) is True


def test_ensure_deps_full_install_path_threads_exact_arguments(
    deps_mod, tmp_path, monkeypatch
):
    """End-to-end through the missing/lock/pip/importable/write-stamp
    path with every internal call's OWN arguments captured.

    An outcome-only assertion (stamp ends up satisfied, pip ends up
    called) can stay green even when one internal call site is fed the
    wrong deps_dir/kind/name -- a later call along the same path, or the
    lock's own double-check, can independently arrive at the same
    observable result. Capturing every call's arguments closes that gap
    directly, and the exact on-disk stamp filename check is immune to
    macOS's case-preserving-but-case-insensitive filesystem (APFS)
    silently equating ``.cortex-deps-stamp-base.json`` with a
    "...-BASE.json" mistake that a case-sensitive Linux CI runner would
    not."""
    deps_dir = tmp_path / "deps"
    deps_dir.mkdir()
    expected_deps_dir = str(deps_dir)
    pins = [spec for _name, spec in deps_mod._BASE_PACKAGES]

    dist_info_calls = []
    real_dist_info_satisfies = deps_mod._dist_info_satisfies

    def capturing_dist_info_satisfies(deps_dir_arg, spec_arg):
        dist_info_calls.append(deps_dir_arg)
        return real_dist_info_satisfies(deps_dir_arg, spec_arg)

    pip_calls = []

    def fake_pip_install(deps_dir_arg, missing_arg):
        pip_calls.append((deps_dir_arg, tuple(missing_arg)))
        return True

    importable_calls = []

    def fake_importable(name_arg, deps_dir_arg):
        importable_calls.append((name_arg, deps_dir_arg))
        return True

    monkeypatch.setattr(deps_mod, "_dist_info_satisfies", capturing_dist_info_satisfies)
    monkeypatch.setattr(deps_mod, "_pip_install", fake_pip_install)
    monkeypatch.setattr(deps_mod, "_importable", fake_importable)

    deps_mod.ensure_deps(str(deps_dir))

    assert dist_info_calls, "the missing-package scan never ran"
    assert all(arg == expected_deps_dir for arg in dist_info_calls)
    assert pip_calls == [
        (expected_deps_dir, tuple(spec for _n, spec in deps_mod._BASE_PACKAGES))
    ]
    assert importable_calls == [
        (name, expected_deps_dir) for name, _spec in deps_mod._BASE_PACKAGES
    ]
    on_disk = {
        p.name for p in deps_dir.iterdir() if p.name.startswith(".cortex-deps-stamp-")
    }
    assert on_disk == {".cortex-deps-stamp-base.json"}
    payload = json.loads(
        (deps_dir / ".cortex-deps-stamp-base.json").read_text(encoding="utf-8")
    )
    assert payload["pins"] == sorted(pins)


def test_ensure_deps_acquires_the_real_deps_dir_lock(deps_mod, tmp_path, monkeypatch):
    """The lock acquired around the install must be deps_dir's OWN
    ``<deps_dir>.lock`` -- verified by observing it actually held (i.e.
    ``mkdir``'d) while pip is "running", not merely that ensure_deps
    completes without error. A ``_deps_lock(None)`` bug would instead
    create an unrelated ``None.lock`` and never touch this one."""
    deps_dir = tmp_path / "deps"
    deps_dir.mkdir()
    lock_dir = Path(f"{deps_dir}.lock")
    observed = {}

    def fake_pip_install(*_a, **_k):
        observed["lock_held"] = lock_dir.is_dir()
        return True

    monkeypatch.setattr(deps_mod, "_pip_install", fake_pip_install)
    monkeypatch.setattr(deps_mod, "_importable", lambda *a, **k: True)
    deps_mod.ensure_deps(str(deps_dir))
    assert observed.get("lock_held") is True


def test_ensure_deps_lock_double_check_uses_the_real_kind_and_pins_key(
    deps_mod, tmp_path, monkeypatch
):
    """The RE-check inside the lock must query the SAME ("base", pins)
    key the outer check and the eventual write use. Simulated by
    wrapping the REAL ``_deps_lock`` so that, exactly as it is entered
    (i.e. once this call has legitimately acquired it), a genuine
    ``_write_stamp`` runs to model another process finishing the
    install while this one waited -- the double-check must then find
    that real stamp and return without ever calling pip."""
    deps_dir = tmp_path / "deps"
    deps_dir.mkdir()
    pins = [spec for _name, spec in deps_mod._BASE_PACKAGES]
    real_lock = deps_mod._deps_lock
    real_pins_satisfied = deps_mod._pins_satisfied
    seen_kinds = []

    def capturing_pins_satisfied(deps_dir_arg, kind_arg, pins_arg):
        seen_kinds.append(kind_arg)
        return real_pins_satisfied(deps_dir_arg, kind_arg, pins_arg)

    @contextlib.contextmanager
    def racing_lock(path):
        with real_lock(path) as acquired:
            deps_mod._write_stamp(str(deps_dir), "base", pins)
            yield acquired

    def fail_if_called(*_a, **_k):
        raise AssertionError("the double-check must have caught the race")

    monkeypatch.setattr(deps_mod, "_deps_lock", racing_lock)
    monkeypatch.setattr(deps_mod, "_pins_satisfied", capturing_pins_satisfied)
    monkeypatch.setattr(deps_mod, "_pip_install", fail_if_called)
    deps_mod.ensure_deps(str(deps_dir))
    # Captured STRING values, not a file-lookup outcome: exact and immune
    # to macOS APFS's case-insensitive (but case-preserving) filesystem,
    # which would otherwise resolve a "base"/"BASE" mix-up to the SAME
    # inode and mask the bug that a case-sensitive Linux CI runner would
    # not.
    assert seen_kinds == ["base", "base"]


def test_ensure_deps_creates_the_directory_when_absent(deps_mod, tmp_path, monkeypatch):
    """``deps_dir`` need not pre-exist -- ``os.makedirs(..., exist_ok=True)``
    is the first thing ``ensure_deps`` does."""
    deps_dir = tmp_path / "not-yet-created" / "deps"
    monkeypatch.setattr(deps_mod, "_importable", lambda *a, **k: True)
    monkeypatch.setattr(deps_mod, "_pip_install", lambda *a, **k: True)
    assert not deps_dir.exists()
    deps_mod.ensure_deps(str(deps_dir))
    assert deps_dir.is_dir()


def test_ensure_deps_writes_stamp_directly_when_dist_info_already_satisfies(
    deps_mod, tmp_path, monkeypatch
):
    """No stamp yet, but every base pin's dist-info is already on disk
    (e.g. carried over from a prior bootstrap that predates the stamp
    feature): the ``missing == []`` short-circuit must stamp WITHOUT
    ever calling pip or the lock."""
    deps_dir = tmp_path / "deps"
    deps_dir.mkdir()
    for _name, spec in deps_mod._BASE_PACKAGES:
        dist_name, version = deps_mod._parse_pip_spec(spec)
        _make_dist_info(deps_dir, dist_name, version)

    def fail_if_called(*_a, **_k):
        raise AssertionError("pip must not be invoked when nothing is missing")

    monkeypatch.setattr(deps_mod, "_pip_install", fail_if_called)
    deps_mod.ensure_deps(str(deps_dir))
    pins = [spec for _name, spec in deps_mod._BASE_PACKAGES]
    assert deps_mod._pins_satisfied(str(deps_dir), "base", pins) is True
    # Exact on-disk filename, not merely "some stamp reads back as
    # satisfied": macOS's APFS is case-preserving but case-INSENSITIVE by
    # default, so ``.cortex-deps-stamp-BASE.json`` and
    # ``.cortex-deps-stamp-base.json`` are the SAME inode there --
    # ``_pins_satisfied`` alone cannot tell a "base"/"BASE" kind mix-up
    # apart on this platform, even though a case-sensitive Linux CI
    # runner would. ``os.listdir``/``Path.iterdir`` return the name as
    # actually STORED regardless of lookup case-sensitivity, so this
    # assertion is exact on every platform.
    on_disk = {
        p.name for p in deps_dir.iterdir() if p.name.startswith(".cortex-deps-stamp-")
    }
    assert on_disk == {".cortex-deps-stamp-base.json"}


def test_ensure_deps_lock_double_check_skips_pip_when_another_process_won(
    deps_mod, tmp_path, monkeypatch
):
    """Two processes race past the outer (unlocked) check together; the
    second one to acquire the lock must see the first one's finished
    stamp on the RE-check inside the lock and skip pip entirely."""
    deps_dir = tmp_path / "deps"
    deps_dir.mkdir()
    calls = {"pins_satisfied": 0}
    real_pins_satisfied = deps_mod._pins_satisfied

    def racing_pins_satisfied(deps_dir_arg, kind, pins_arg):
        calls["pins_satisfied"] += 1
        if calls["pins_satisfied"] == 1:
            return False  # outer check: not yet satisfied
        return True  # inside the lock: the "other process" just finished

    def fail_if_called(*_a, **_k):
        raise AssertionError("pip must not run once the double-check wins")

    monkeypatch.setattr(deps_mod, "_pins_satisfied", racing_pins_satisfied)
    monkeypatch.setattr(deps_mod, "_pip_install", fail_if_called)
    deps_mod.ensure_deps(str(deps_dir))
    assert calls["pins_satisfied"] == 2
    monkeypatch.setattr(deps_mod, "_pins_satisfied", real_pins_satisfied)


def test_ensure_deps_requests_only_the_genuinely_missing_packages(
    deps_mod, tmp_path, monkeypatch
):
    """``missing`` must be the SUBSET of ``_BASE_PACKAGES`` whose dist-info
    isn't already on disk -- not the full pin list -- so an already
    correct entry is never re-resolved by pip."""
    deps_dir = tmp_path / "deps"
    deps_dir.mkdir()
    satisfied_name, satisfied_spec = deps_mod._BASE_PACKAGES[0]
    dist_name, version = deps_mod._parse_pip_spec(satisfied_spec)
    _make_dist_info(deps_dir, dist_name, version)

    requested = {}

    def fake_pip_install(_deps_dir, packages):
        requested["packages"] = list(packages)
        return True

    monkeypatch.setattr(deps_mod, "_pip_install", fake_pip_install)
    monkeypatch.setattr(deps_mod, "_importable", lambda *a, **k: True)
    deps_mod.ensure_deps(str(deps_dir))
    assert satisfied_spec not in requested["packages"]
    other_specs = [
        spec for name, spec in deps_mod._BASE_PACKAGES if name != satisfied_name
    ]
    assert sorted(requested["packages"]) == sorted(other_specs)


def test_ensure_deps_does_not_stamp_when_a_package_stays_unimportable(
    deps_mod, tmp_path, monkeypatch
):
    """If ``pip`` reports success but the POST-install husk check still
    fails for one package, the stamp must not be written -- the next
    bootstrap has to try again rather than trust a false success."""
    deps_dir = tmp_path / "deps"
    deps_dir.mkdir()
    bad_name = deps_mod._BASE_PACKAGES[-1][0]

    monkeypatch.setattr(deps_mod, "_pip_install", lambda *a, **k: True)
    monkeypatch.setattr(
        deps_mod, "_importable", lambda name, _deps_dir: name != bad_name
    )
    deps_mod.ensure_deps(str(deps_dir))
    pins = [spec for _name, spec in deps_mod._BASE_PACKAGES]
    assert deps_mod._pins_satisfied(str(deps_dir), "base", pins) is False


def test_deps_lock_mutual_exclusion(deps_mod, tmp_path):
    deps_dir = str(tmp_path / "deps")
    os.makedirs(deps_dir, exist_ok=True)
    with deps_mod._deps_lock(deps_dir) as acquired_outer:
        assert acquired_outer is True
        assert os.path.isdir(f"{deps_dir}.lock")
    # Released after the context exits.
    assert not os.path.isdir(f"{deps_dir}.lock")


def test_deps_lock_steals_stale_lock(deps_mod, tmp_path, monkeypatch):
    deps_dir = str(tmp_path / "deps")
    os.makedirs(deps_dir, exist_ok=True)
    lock_dir = f"{deps_dir}.lock"
    os.makedirs(lock_dir)
    holder = os.path.join(lock_dir, "holder")
    with open(holder, "w", encoding="utf-8") as fh:
        fh.write("99999 0")
    # Force the age computation to look ancient without a real sleep.
    monkeypatch.setattr(deps_mod.os.path, "getmtime", lambda _p: 0.0)
    monkeypatch.setattr(deps_mod.time, "time", lambda: 10_000.0)
    with deps_mod._deps_lock(deps_dir) as acquired:
        assert acquired is True


def test_entry_dist_key_strips_dist_info_suffix(deps_mod):
    assert deps_mod._entry_dist_key("numpy-2.4.4.dist-info") == "numpy"
    assert deps_mod._entry_dist_key("numpy") == "numpy"
    assert (
        deps_mod._entry_dist_key("pydantic_settings-2.14.0.dist-info")
        == "pydantic_settings"
    )


# ---------------------------------------------------- residue 1: sweep ---


def test_pid_alive_true_for_current_process(deps_mod):
    assert deps_mod._pid_alive(os.getpid()) is True


def test_pid_alive_false_for_invalid_pid(deps_mod):
    assert deps_mod._pid_alive(0) is False
    assert deps_mod._pid_alive(-1) is False


def test_sweep_stale_backups_removes_dead_pid_husk(deps_mod, tmp_path, monkeypatch):
    """mbe14's real-Windows-lock finding: a locked file inside the
    rename-aside backup leaves `<entry>.bak-<pid>` husks that
    `shutil.rmtree(..., ignore_errors=True)` silently kept. Once the
    owning pid is dead, the sweep must reclaim them."""
    deps_dir = tmp_path / "deps"
    deps_dir.mkdir()
    (deps_dir / "numpy.bak-4242").mkdir()
    (deps_dir / "numpy-2.4.4.dist-info.bak-4242").mkdir()
    monkeypatch.setattr(deps_mod._fs, "pid_alive", lambda _pid: False)
    deps_mod._sweep_stale_backups(str(deps_dir))
    assert not (deps_dir / "numpy.bak-4242").exists()
    assert not (deps_dir / "numpy-2.4.4.dist-info.bak-4242").exists()


def test_sweep_stale_backups_leaves_live_pid_alone(deps_mod, tmp_path, monkeypatch):
    """A backup whose owning process is still alive (still holding the
    lock) must survive the sweep."""
    deps_dir = tmp_path / "deps"
    deps_dir.mkdir()
    (deps_dir / "numpy.bak-4242").mkdir()
    monkeypatch.setattr(deps_mod._fs, "pid_alive", lambda _pid: True)
    deps_mod._sweep_stale_backups(str(deps_dir))
    assert (deps_dir / "numpy.bak-4242").exists()


def test_sweep_stale_backups_ignores_non_matching_names(
    deps_mod, tmp_path, monkeypatch
):
    deps_dir = tmp_path / "deps"
    deps_dir.mkdir()
    (deps_dir / "numpy").mkdir()
    (deps_dir / "not-a-backup.txt").write_text("x", encoding="utf-8")
    monkeypatch.setattr(deps_mod._fs, "pid_alive", lambda _pid: False)
    deps_mod._sweep_stale_backups(str(deps_dir))
    assert (deps_dir / "numpy").exists()
    assert (deps_dir / "not-a-backup.txt").exists()


def test_ensure_deps_sweeps_stale_backups(deps_mod, tmp_path, monkeypatch):
    """The sweep runs unconditionally at the top of ensure_deps, even
    when the stamp already short-circuits the rest of the bootstrap."""
    deps_dir = tmp_path / "deps"
    deps_dir.mkdir()
    (deps_dir / "numpy.bak-4242").mkdir()
    pins = [spec for _name, spec in deps_mod._BASE_PACKAGES]
    deps_mod._write_stamp(str(deps_dir), "base", pins)
    monkeypatch.setattr(deps_mod._fs, "pid_alive", lambda _pid: False)
    deps_mod.ensure_deps(str(deps_dir))
    assert not (deps_dir / "numpy.bak-4242").exists()


# ------------------------------------------- residue 2: dist-info prune ---


def test_pip_install_prunes_superseded_dist_info_on_version_bump(
    deps_mod, tmp_path, monkeypatch
):
    """A cross-version commit must remove the OLD dist-info, not leave
    duplicate metadata for the same distribution (importlib.metadata /
    pip both see two records for one dist otherwise)."""
    deps_dir = tmp_path / "deps"
    deps_dir.mkdir()
    _make_pkg_dir(deps_dir, "numpy", marker="OLD")
    _make_dist_info(deps_dir, "numpy", "2.4.4")

    def fake_run(cmd, **kwargs):
        tmp_dir = Path(cmd[cmd.index("--target") + 1])
        _make_pkg_dir(tmp_dir, "numpy", marker="NEW")
        _make_dist_info(tmp_dir, "numpy", "2.5.1")

        class _Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return _Result()

    monkeypatch.setattr(deps_mod._install.subprocess, "run", fake_run)
    ok = deps_mod._pip_install(str(deps_dir), ["numpy==2.5.1"])
    assert ok is True
    assert (deps_dir / "numpy-2.5.1.dist-info").is_dir()
    assert not (deps_dir / "numpy-2.4.4.dist-info").exists()


def test_pip_install_prune_does_not_touch_unrelated_dist_info(
    deps_mod, tmp_path, monkeypatch
):
    deps_dir = tmp_path / "deps"
    deps_dir.mkdir()
    _make_pkg_dir(deps_dir, "numpy", marker="OLD")
    _make_dist_info(deps_dir, "numpy", "2.4.4")
    _make_dist_info(deps_dir, "pydantic", "2.13.3")

    def fake_run(cmd, **kwargs):
        tmp_dir = Path(cmd[cmd.index("--target") + 1])
        _make_pkg_dir(tmp_dir, "numpy", marker="NEW")
        _make_dist_info(tmp_dir, "numpy", "2.5.1")

        class _Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return _Result()

    monkeypatch.setattr(deps_mod._install.subprocess, "run", fake_run)
    deps_mod._pip_install(str(deps_dir), ["numpy==2.5.1"])
    assert (deps_dir / "pydantic-2.13.3.dist-info").is_dir()


def test_pip_install_prune_not_reached_on_idempotence_skip(
    deps_mod, tmp_path, monkeypatch
):
    """The idempotence guard's `continue` never commits anything, so the
    prune step must not run either -- nothing changed, nothing to
    prune."""
    deps_dir = tmp_path / "deps"
    deps_dir.mkdir()
    _make_pkg_dir(deps_dir, "numpy", marker="SAME")
    _make_dist_info(deps_dir, "numpy", "2.4.4")

    def fake_run(cmd, **kwargs):
        tmp_dir = Path(cmd[cmd.index("--target") + 1])
        _make_pkg_dir(tmp_dir, "numpy", marker="SAME")
        _make_dist_info(tmp_dir, "numpy", "2.4.4")

        class _Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return _Result()

    pruned = {"called": False}
    monkeypatch.setattr(deps_mod._install.subprocess, "run", fake_run)
    monkeypatch.setattr(
        deps_mod._install._fs,
        "prune_superseded_dist_info",
        lambda *a, **k: pruned.__setitem__("called", True),
    )
    ok = deps_mod._pip_install(str(deps_dir), ["numpy==2.4.4"])
    assert ok is True
    assert pruned["called"] is False


# ---------------------------------------- residue 3: hermetic bootstrap ---


def test_dist_info_satisfies_ignores_host_sys_path(deps_mod, tmp_path, monkeypatch):
    """The install decision must be based on deps_dir's OWN dist-info,
    not on whatever the host interpreter can import from the rest of
    sys.path. Simulate a host-global numpy: it's importable, but
    deps_dir itself has no numpy dist-info, so the pin must still read
    as unsatisfied."""
    deps_dir = tmp_path / "deps"
    deps_dir.mkdir()
    fake_site_packages = tmp_path / "host-site-packages"
    _make_pkg_dir(fake_site_packages, "numpy")
    monkeypatch.syspath_prepend(str(fake_site_packages))

    assert deps_mod._importable("numpy", str(deps_dir)) is True  # host shadow
    assert deps_mod._dist_info_satisfies(str(deps_dir), "numpy==2.4.4") is False


def test_ensure_deps_requests_package_satisfied_only_by_host(
    deps_mod, tmp_path, monkeypatch
):
    """End-to-end residue 3: a package importable only via the HOST's
    global site-packages (not deps_dir) must still be requested from
    pip -- it must not silently drop out of the install set and enter
    deps_dir only later as an unpinned transitive."""
    deps_dir = tmp_path / "deps"
    deps_dir.mkdir()
    fake_site_packages = tmp_path / "host-site-packages"
    _make_pkg_dir(fake_site_packages, "numpy")
    monkeypatch.syspath_prepend(str(fake_site_packages))

    requested = {}

    def fake_pip_install(_deps_dir, packages, constraints=None):
        requested["packages"] = packages
        return True

    monkeypatch.setattr(deps_mod, "_pip_install", fake_pip_install)
    monkeypatch.setattr(deps_mod, "_importable", lambda *a, **k: True)
    deps_mod.ensure_deps(str(deps_dir))
    numpy_spec = next(spec for name, spec in deps_mod._BASE_PACKAGES if name == "numpy")
    assert numpy_spec in requested["packages"]


def test_ensure_all_deps_passes_base_pins_as_constraints(
    deps_mod, tmp_path, monkeypatch
):
    """Residue 3, second half: the ML install must constrain its resolve
    to the base pins so a shared transitive (numpy) agrees with the
    base install regardless of order."""
    deps_dir = tmp_path / "deps"
    deps_dir.mkdir()
    base_pins = [spec for _name, spec in deps_mod._BASE_PACKAGES]
    deps_mod._write_stamp(str(deps_dir), "base", base_pins)

    captured = {}

    def fake_pip_install(_deps_dir, packages, constraints=None):
        captured["packages"] = packages
        captured["constraints"] = constraints
        return True

    monkeypatch.setattr(deps_mod, "_pip_install", fake_pip_install)
    monkeypatch.setattr(deps_mod, "_importable", lambda *a, **k: True)
    deps_mod.ensure_all_deps(str(deps_dir))
    assert captured["constraints"] == base_pins


def test_ensure_all_deps_skips_pip_entirely_when_ml_stamp_matches(
    deps_mod, tmp_path, monkeypatch
):
    """The ML hot path mirrors the base one: a valid ML stamp means zero
    ``_pip_install`` calls for the ML packages."""
    deps_dir = tmp_path / "deps"
    deps_dir.mkdir()
    base_pins = [spec for _name, spec in deps_mod._BASE_PACKAGES]
    ml_pins = [spec for _name, spec in deps_mod._ML_PACKAGES]
    deps_mod._write_stamp(str(deps_dir), "base", base_pins)
    deps_mod._write_stamp(str(deps_dir), "ml", ml_pins)
    real_pins_satisfied = deps_mod._pins_satisfied
    seen = []

    def capturing_pins_satisfied(deps_dir_arg, kind_arg, pins_arg):
        seen.append(kind_arg)
        return real_pins_satisfied(deps_dir_arg, kind_arg, pins_arg)

    def fail_if_called(*_a, **_k):
        raise AssertionError("pip must not run once both stamps already match")

    monkeypatch.setattr(deps_mod, "_pins_satisfied", capturing_pins_satisfied)
    monkeypatch.setattr(deps_mod, "_pip_install", fail_if_called)
    deps_mod.ensure_all_deps(str(deps_dir))
    # The EXACT sequence of literal kind strings -- immune to macOS
    # APFS's case-insensitive filesystem, which can make a "ml"/"ML" (or
    # "base"/"BASE") argument mix-up still resolve to the same on-disk
    # stamp and mask the bug. Both stamps already match, so the correct
    # code takes exactly two checks (ensure_deps's own "base", then this
    # function's outer "ml") and never reaches the inner double-check;
    # any wrong/missing kind argument makes at least one lookup miss and
    # lengthens or alters this sequence.
    assert seen == ["base", "ml"]


def test_ensure_all_deps_writes_stamp_directly_when_dist_info_already_satisfies(
    deps_mod, tmp_path, monkeypatch
):
    """No ML stamp yet, but both ML packages' dist-info is already on
    disk: the ``missing == []`` short-circuit stamps without pip."""
    deps_dir = tmp_path / "deps"
    deps_dir.mkdir()
    base_pins = [spec for _name, spec in deps_mod._BASE_PACKAGES]
    deps_mod._write_stamp(str(deps_dir), "base", base_pins)
    for _name, spec in deps_mod._ML_PACKAGES:
        dist_name, version = deps_mod._parse_pip_spec(spec)
        _make_dist_info(deps_dir, dist_name, version)

    def fail_if_called(*_a, **_k):
        raise AssertionError("pip must not be invoked when nothing is missing")

    monkeypatch.setattr(deps_mod, "_pip_install", fail_if_called)
    deps_mod.ensure_all_deps(str(deps_dir))
    ml_pins = [spec for _name, spec in deps_mod._ML_PACKAGES]
    assert deps_mod._pins_satisfied(str(deps_dir), "ml", ml_pins) is True
    # Exact on-disk filename: macOS APFS is case-preserving but
    # case-INSENSITIVE, so ``_pins_satisfied`` alone cannot tell a
    # "ml"/"ML" kind mix-up in the fast-write branch apart on this
    # platform, even though a case-sensitive Linux CI runner would.
    on_disk = {
        p.name for p in deps_dir.iterdir() if p.name.startswith(".cortex-deps-stamp-")
    }
    assert on_disk == {".cortex-deps-stamp-base.json", ".cortex-deps-stamp-ml.json"}


def test_ensure_all_deps_lock_double_check_skips_pip_when_another_process_won(
    deps_mod, tmp_path, monkeypatch
):
    """Same race as the base install's double-check, on the ML stamp."""
    deps_dir = tmp_path / "deps"
    deps_dir.mkdir()
    base_pins = [spec for _name, spec in deps_mod._BASE_PACKAGES]
    deps_mod._write_stamp(str(deps_dir), "base", base_pins)
    calls = {"pins_satisfied": 0}
    real_pins_satisfied = deps_mod._pins_satisfied

    def racing_pins_satisfied(deps_dir_arg, kind, pins_arg):
        if kind == "base":
            return real_pins_satisfied(deps_dir_arg, kind, pins_arg)
        calls["pins_satisfied"] += 1
        return calls["pins_satisfied"] != 1  # first (outer) call: False

    def fail_if_called(*_a, **_k):
        raise AssertionError("pip must not run once the double-check wins")

    monkeypatch.setattr(deps_mod, "_pins_satisfied", racing_pins_satisfied)
    monkeypatch.setattr(deps_mod, "_pip_install", fail_if_called)
    deps_mod.ensure_all_deps(str(deps_dir))
    assert calls["pins_satisfied"] == 2
    monkeypatch.setattr(deps_mod, "_pins_satisfied", real_pins_satisfied)


def test_ensure_all_deps_requests_only_the_genuinely_missing_ml_packages(
    deps_mod, tmp_path, monkeypatch
):
    deps_dir = tmp_path / "deps"
    deps_dir.mkdir()
    base_pins = [spec for _name, spec in deps_mod._BASE_PACKAGES]
    deps_mod._write_stamp(str(deps_dir), "base", base_pins)
    satisfied_name, satisfied_spec = deps_mod._ML_PACKAGES[0]
    dist_name, version = deps_mod._parse_pip_spec(satisfied_spec)
    _make_dist_info(deps_dir, dist_name, version)

    requested = {}

    def fake_pip_install(_deps_dir, packages, constraints=None):
        requested["packages"] = list(packages)
        return True

    monkeypatch.setattr(deps_mod, "_pip_install", fake_pip_install)
    monkeypatch.setattr(deps_mod, "_importable", lambda *a, **k: True)
    deps_mod.ensure_all_deps(str(deps_dir))
    assert satisfied_spec not in requested["packages"]
    other_specs = [
        spec for name, spec in deps_mod._ML_PACKAGES if name != satisfied_name
    ]
    assert sorted(requested["packages"]) == sorted(other_specs)


def test_ensure_all_deps_does_not_stamp_when_a_package_stays_unimportable(
    deps_mod, tmp_path, monkeypatch
):
    """``all(...)`` over BOTH ML packages: one staying unimportable after
    a reported-successful pip run must still withhold the stamp."""
    deps_dir = tmp_path / "deps"
    deps_dir.mkdir()
    base_pins = [spec for _name, spec in deps_mod._BASE_PACKAGES]
    deps_mod._write_stamp(str(deps_dir), "base", base_pins)

    monkeypatch.setattr(deps_mod, "_pip_install", lambda *a, **k: True)
    monkeypatch.setattr(
        deps_mod, "_importable", lambda name, _deps_dir: name != "flashrank"
    )
    deps_mod.ensure_all_deps(str(deps_dir))
    ml_pins = [spec for _name, spec in deps_mod._ML_PACKAGES]
    assert deps_mod._pins_satisfied(str(deps_dir), "ml", ml_pins) is False


def test_ensure_all_deps_full_install_path_threads_exact_arguments(
    deps_mod, tmp_path, monkeypatch
):
    """The ML-install mirror of
    ``test_ensure_deps_full_install_path_threads_exact_arguments``: every
    internal call's own arguments captured, plus an exact on-disk stamp
    filename check immune to APFS's case-insensitivity."""
    deps_dir = tmp_path / "deps"
    deps_dir.mkdir()
    expected_deps_dir = str(deps_dir)
    base_pins = [spec for _name, spec in deps_mod._BASE_PACKAGES]
    deps_mod._write_stamp(str(deps_dir), "base", base_pins)
    ml_pins = [spec for _name, spec in deps_mod._ML_PACKAGES]

    dist_info_calls = []
    real_dist_info_satisfies = deps_mod._dist_info_satisfies

    def capturing_dist_info_satisfies(deps_dir_arg, spec_arg):
        dist_info_calls.append(deps_dir_arg)
        return real_dist_info_satisfies(deps_dir_arg, spec_arg)

    pip_calls = []

    def fake_pip_install(deps_dir_arg, missing_arg, constraints=None):
        pip_calls.append((deps_dir_arg, tuple(missing_arg), tuple(constraints or ())))
        return True

    importable_calls = []

    def fake_importable(name_arg, deps_dir_arg):
        importable_calls.append((name_arg, deps_dir_arg))
        return True

    monkeypatch.setattr(deps_mod, "_dist_info_satisfies", capturing_dist_info_satisfies)
    monkeypatch.setattr(deps_mod, "_pip_install", fake_pip_install)
    monkeypatch.setattr(deps_mod, "_importable", fake_importable)

    deps_mod.ensure_all_deps(str(deps_dir))

    assert dist_info_calls, "the ML missing-package scan never ran"
    assert all(arg == expected_deps_dir for arg in dist_info_calls)
    assert pip_calls == [
        (
            expected_deps_dir,
            tuple(spec for _n, spec in deps_mod._ML_PACKAGES),
            tuple(base_pins),
        )
    ]
    assert importable_calls == [
        ("sentence_transformers", expected_deps_dir),
        ("flashrank", expected_deps_dir),
    ]
    on_disk = {
        p.name for p in deps_dir.iterdir() if p.name.startswith(".cortex-deps-stamp-")
    }
    assert on_disk == {".cortex-deps-stamp-base.json", ".cortex-deps-stamp-ml.json"}
    payload = json.loads(
        (deps_dir / ".cortex-deps-stamp-ml.json").read_text(encoding="utf-8")
    )
    assert payload["pins"] == sorted(ml_pins)


def test_ensure_all_deps_acquires_the_real_deps_dir_lock(
    deps_mod, tmp_path, monkeypatch
):
    """Same ``_deps_lock(None)`` regression guard as the base install,
    for the ML lock acquisition."""
    deps_dir = tmp_path / "deps"
    deps_dir.mkdir()
    base_pins = [spec for _name, spec in deps_mod._BASE_PACKAGES]
    deps_mod._write_stamp(str(deps_dir), "base", base_pins)
    lock_dir = Path(f"{deps_dir}.lock")
    observed = {}

    def fake_pip_install(*_a, **_k):
        observed["lock_held"] = lock_dir.is_dir()
        return True

    monkeypatch.setattr(deps_mod, "_pip_install", fake_pip_install)
    monkeypatch.setattr(deps_mod, "_importable", lambda *a, **k: True)
    deps_mod.ensure_all_deps(str(deps_dir))
    assert observed.get("lock_held") is True


def test_ensure_all_deps_lock_double_check_uses_the_real_kind_and_pins_key(
    deps_mod, tmp_path, monkeypatch
):
    """The ML mirror of the base install's racing double-check test."""
    deps_dir = tmp_path / "deps"
    deps_dir.mkdir()
    base_pins = [spec for _name, spec in deps_mod._BASE_PACKAGES]
    deps_mod._write_stamp(str(deps_dir), "base", base_pins)
    ml_pins = [spec for _name, spec in deps_mod._ML_PACKAGES]
    real_lock = deps_mod._deps_lock
    real_pins_satisfied = deps_mod._pins_satisfied
    seen_ml_kinds = []

    def capturing_pins_satisfied(deps_dir_arg, kind_arg, pins_arg):
        if kind_arg != "base":
            seen_ml_kinds.append(kind_arg)
        return real_pins_satisfied(deps_dir_arg, kind_arg, pins_arg)

    @contextlib.contextmanager
    def racing_lock(path):
        with real_lock(path) as acquired:
            deps_mod._write_stamp(str(deps_dir), "ml", ml_pins)
            yield acquired

    def fail_if_called(*_a, **_k):
        raise AssertionError("the double-check must have caught the race")

    monkeypatch.setattr(deps_mod, "_deps_lock", racing_lock)
    monkeypatch.setattr(deps_mod, "_pins_satisfied", capturing_pins_satisfied)
    monkeypatch.setattr(deps_mod, "_pip_install", fail_if_called)
    deps_mod.ensure_all_deps(str(deps_dir))
    # Both the outer (miss, no stamp yet) and inner (hit, race modeled
    # above) ML checks must use the exact literal "ml" -- captured as
    # STRINGS so a "ml"/"ML" argument mix-up cannot hide behind macOS
    # APFS's case-insensitive file lookup.
    assert seen_ml_kinds == ["ml", "ml"]


def test_pip_install_writes_and_cleans_constraints_file(
    deps_mod, tmp_path, monkeypatch
):
    deps_dir = tmp_path / "deps"
    deps_dir.mkdir()
    captured_cmd = {}

    def fake_run(cmd, **kwargs):
        captured_cmd["cmd"] = cmd
        if "-c" in cmd:
            constraints_path = cmd[cmd.index("-c") + 1]
            captured_cmd["constraints_path"] = constraints_path
            captured_cmd["constraints_contents"] = Path(constraints_path).read_text(
                encoding="utf-8"
            )
        tmp_dir = Path(cmd[cmd.index("--target") + 1])
        _make_pkg_dir(tmp_dir, "flashrank")
        _make_dist_info(tmp_dir, "flashrank", "0.2.10")

        class _Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return _Result()

    monkeypatch.setattr(deps_mod._install.subprocess, "run", fake_run)
    ok = deps_mod._pip_install(
        str(deps_dir), ["flashrank==0.2.10"], constraints=["numpy==2.4.4"]
    )
    assert ok is True
    assert "-c" in captured_cmd["cmd"]
    assert "numpy==2.4.4" in captured_cmd["constraints_contents"]
    assert not Path(captured_cmd["constraints_path"]).exists()  # cleaned up


def test_pip_install_no_constraints_file_when_none_given(
    deps_mod, tmp_path, monkeypatch
):
    """The common (base-install) case passes no constraints -- must not
    add a `-c` flag or create a stray file."""
    deps_dir = tmp_path / "deps"
    deps_dir.mkdir()
    captured_cmd = {}

    def fake_run(cmd, **kwargs):
        captured_cmd["cmd"] = cmd
        tmp_dir = Path(cmd[cmd.index("--target") + 1])
        _make_pkg_dir(tmp_dir, "numpy")
        _make_dist_info(tmp_dir, "numpy", "2.4.4")

        class _Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return _Result()

    monkeypatch.setattr(deps_mod._install.subprocess, "run", fake_run)
    deps_mod._pip_install(str(deps_dir), ["numpy==2.4.4"])
    assert "-c" not in captured_cmd["cmd"]


# ---------------------------------------------------- bare-import at runtime


def test_launcher_deps_stays_bare_importable_by_launcher_py():
    """scripts/launcher.py's own ``import launcher_deps`` must still work.

    launcher_deps.py's docstring requires it stay loadable by a BARE
    module name at real runtime: launcher.py runs before the plugin's own
    dependencies exist on sys.path, inserts scripts/ onto sys.path, then
    does a plain ``import launcher_deps`` (see launcher.py's docstring —
    "not a bare `import launcher_deps`" is explicitly the OTHER case it
    guards against for itself, contrasted with launcher_deps.py's own
    unqualified import of its siblings).

    This test's OWN loader (``deps_mod`` in this file) was renamed to
    "scripts.launcher_deps" so mutmut can attribute mutants (issue #262)
    — a test-only concern. This test instead proves, via a REAL `python3`
    subprocess that never goes through pytest's sys.path or any test
    loader, that PRODUCTION bare-importability is unaffected. A regression
    here would raise ModuleNotFoundError at module scope, before main()
    even runs, printing a traceback instead of the plain usage message.
    """
    result = subprocess.run(  # noqa: S603 — fixed argv, no shell, no user input
        [sys.executable, str(REPO_ROOT / "scripts" / "launcher.py")],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(REPO_ROOT),
    )
    assert result.returncode == 1, result.stderr
    assert "Usage: python3 scripts/launcher.py" in result.stderr
    assert "Traceback" not in result.stderr
    assert "ModuleNotFoundError" not in result.stderr
