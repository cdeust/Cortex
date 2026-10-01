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

import importlib.util
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


_SET = ("--only-group", "launcher-base")


def _route_install(monkeypatch, deps_mod, fake_run) -> None:
    """Send the locked install to ``fake_run``, with the real scratch target."""
    monkeypatch.setattr(
        deps_mod._install._uv,
        "install_locked_set",
        lambda _deps_dir, _set_args, target: fake_run(
            ["uv", "pip", "install", "--target", target]
        ),
    )


def _make_dist_info(root: Path, dist_name: str, version: str) -> None:
    """A ``*.dist-info`` whose ``RECORD`` lists the ``dist_name`` package, as
    pip writes one for every install (the guard reads owners from it)."""
    d = root / f"{dist_name}-{version}.dist-info"
    d.mkdir(parents=True, exist_ok=True)
    (d / "METADATA").write_text(
        f"Name: {dist_name}\nVersion: {version}\n", encoding="utf-8"
    )
    listed = [f"{dist_name}/__init__.py", f"{d.name}/METADATA", f"{d.name}/RECORD"]
    (d / "RECORD").write_text("".join(f"{p},,\n" for p in listed), encoding="utf-8")


def _make_pkg_dir(root: Path, pkg_name: str, marker: str = "x") -> None:
    d = root / pkg_name
    d.mkdir(parents=True, exist_ok=True)
    (d / "__init__.py").write_text(f"# {marker}\n", encoding="utf-8")


# ---------------------------------------------------------------- helpers ---


def test_normalize_dist_key_folds_separators(deps_mod):
    assert deps_mod._normalize_dist_key("pydantic-settings") == "pydantic_settings"
    assert deps_mod._normalize_dist_key("pydantic_settings") == "pydantic_settings"
    assert deps_mod._normalize_dist_key("PyDantic.Settings") == "pydantic_settings"


def test_dist_info_versions_scans_only_dist_info_dirs(deps_mod, tmp_path):
    _make_dist_info(tmp_path, "numpy", "2.4.4")
    _make_pkg_dir(tmp_path, "numpy")
    (tmp_path / "not_a_dist_info").mkdir()
    versions = deps_mod._dist_info_versions(str(tmp_path))
    assert versions == {"numpy": "2.4.4"}


def test_dist_info_versions_missing_dir_returns_empty(deps_mod, tmp_path):
    assert deps_mod._dist_info_versions(str(tmp_path / "nope")) == {}


def _listdir_with_last(monkeypatch, last: str) -> None:
    """Pin ``os.listdir`` to return ``last`` after its siblings."""
    real = os.listdir
    monkeypatch.setattr(
        os, "listdir", lambda path: sorted(real(path), key=lambda n: n == last)
    )


@pytest.mark.parametrize("last", ["numpy-2.2.6.dist-info", "numpy-2.4.4.dist-info"])
def test_dist_info_versions_omits_a_distribution_with_several_dist_infos(
    deps_mod, tmp_path, monkeypatch, last
):
    """Issue #573: two ``*.dist-info`` for one distribution leave its
    installed version unknown, whichever one the directory lists last."""
    _make_dist_info(tmp_path, "numpy", "2.2.6")
    _make_dist_info(tmp_path, "numpy", "2.4.4")
    _make_dist_info(tmp_path, "flashrank", "0.2.10")
    _listdir_with_last(monkeypatch, last)
    assert deps_mod._dist_info_versions(str(tmp_path)) == {"flashrank": "0.2.10"}


# ----------------------------------------------------- foreign-ABI detection ---


def test_is_foreign_abi_extension_true_for_a_different_interpreter_tag(deps_mod):
    fs = deps_mod._fs
    assert (
        fs.is_foreign_abi_extension(
            "speedups.cpython-313-darwin.so", current_suffix=".cpython-314-darwin.so"
        )
        is True
    )


def test_is_foreign_abi_extension_false_when_tag_matches_current(deps_mod):
    fs = deps_mod._fs
    assert (
        fs.is_foreign_abi_extension(
            "speedups.cpython-314-darwin.so", current_suffix=".cpython-314-darwin.so"
        )
        is False
    )


def test_is_foreign_abi_extension_false_for_untagged_or_non_extension_names(deps_mod):
    """The stable-ABI (`.abi3.so`) and plain `.so`/`.pyd` forms carry no
    interpreter tag at all -- cross-version by construction -- and a
    `.py` source file is not an extension in the first place."""
    fs = deps_mod._fs
    for name in (
        "foo.abi3.so",
        "foo.so",
        "foo.pyd",
        "__init__.py",
        "cffi-1.17.1.dist-info",
    ):
        assert (
            fs.is_foreign_abi_extension(name, current_suffix=".cpython-314-darwin.so")
            is False
        ), name


def test_entry_has_foreign_abi_extension_walks_nested_directories(deps_mod, tmp_path):
    fs = deps_mod._fs
    pkg = tmp_path / "websockets"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("# x\n", encoding="utf-8")
    (pkg / "speedups.cpython-313-darwin.so").write_bytes(b"old")
    assert (
        fs.entry_has_foreign_abi_extension(
            str(pkg), current_suffix=".cpython-314-darwin.so"
        )
        is True
    )


def test_entry_has_foreign_abi_extension_false_for_missing_path(deps_mod, tmp_path):
    fs = deps_mod._fs
    assert fs.entry_has_foreign_abi_extension(str(tmp_path / "nope")) is False


def test_prune_foreign_abi_extensions_removes_only_foreign_top_level_files(
    deps_mod, tmp_path
):
    """Prunes a stale top-level extension; leaves the current-ABI file
    and a same-tagged file nested inside a package directory (that
    shape is handled by the ABI-aware idempotence guard replacing the
    whole directory, not by this top-level sweep)."""
    fs = deps_mod._fs
    deps_dir = tmp_path / "deps"
    deps_dir.mkdir()
    (deps_dir / "_cffi_backend.cpython-313-darwin.so").write_bytes(b"old")
    (deps_dir / "_cffi_backend.cpython-314-darwin.so").write_bytes(b"new")
    pkg = deps_dir / "websockets"
    pkg.mkdir()
    (pkg / "speedups.cpython-313-darwin.so").write_bytes(b"nested-old")

    fs.prune_foreign_abi_extensions(
        str(deps_dir), current_suffix=".cpython-314-darwin.so"
    )

    assert not (deps_dir / "_cffi_backend.cpython-313-darwin.so").exists()
    assert (deps_dir / "_cffi_backend.cpython-314-darwin.so").exists()
    assert (pkg / "speedups.cpython-313-darwin.so").exists()  # untouched: not top-level


def test_prune_foreign_abi_extensions_missing_dir_is_a_silent_no_op(deps_mod, tmp_path):
    deps_mod._fs.prune_foreign_abi_extensions(str(tmp_path / "nope"))  # must not raise


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

    _route_install(monkeypatch, deps_mod, fake_run)
    ok = deps_mod._install_locked_set(str(deps_dir), _SET)
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

    _route_install(monkeypatch, deps_mod, fake_run)
    ok = deps_mod._install_locked_set(str(deps_dir), _SET)
    assert ok is True
    assert "NEW" in (deps_dir / "numpy" / "__init__.py").read_text(encoding="utf-8")
    assert (deps_dir / "numpy-2.4.4.dist-info").is_dir()
    # Residue 2 fix: the superseded numpy-2.2.6.dist-info is pruned right
    # after the commit, not left as duplicate metadata for one dist. See
    # test_pip_install_prunes_superseded_dist_info_on_version_bump below
    # for the dedicated coverage of this behavior.
    assert not (deps_dir / "numpy-2.2.6.dist-info").exists()


def test_pip_install_repairs_old_code_under_new_metadata(
    deps_mod, tmp_path, monkeypatch
):
    """Issue #573: a direct ``--target`` upgrade left the old package
    directory next to both the old and the new ``*.dist-info``. With the
    new one listed last, the idempotence guard read the pinned version and
    skipped the stale code; it must replace it instead."""
    deps_dir = tmp_path / "deps"
    deps_dir.mkdir()
    _make_pkg_dir(deps_dir, "numpy", marker="OLD")
    _make_dist_info(deps_dir, "numpy", "2.2.6")
    _make_dist_info(deps_dir, "numpy", "2.4.4")
    _listdir_with_last(monkeypatch, "numpy-2.4.4.dist-info")

    def fake_run(cmd, **kwargs):
        tmp_dir = Path(cmd[cmd.index("--target") + 1])
        _make_pkg_dir(tmp_dir, "numpy", marker="NEW")
        _make_dist_info(tmp_dir, "numpy", "2.4.4")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    _route_install(monkeypatch, deps_mod, fake_run)
    assert deps_mod._install_locked_set(str(deps_dir), _SET) is True
    assert "NEW" in (deps_dir / "numpy" / "__init__.py").read_text(encoding="utf-8")
    dist_infos = sorted(p.name for p in deps_dir.glob("numpy-*.dist-info"))
    assert dist_infos == ["numpy-2.4.4.dist-info"]


def test_pip_install_replaces_entry_with_foreign_abi_extension_despite_matching_version(
    deps_mod, tmp_path, monkeypatch
):
    """Issue #540, first shape: dest's ``websockets`` package still
    carries an extension module built for a PREVIOUS interpreter
    (``cpython-313``), and pip re-resolves the SAME version this run
    (nothing changed on PyPI). The version-only guard would call this
    "already satisfied" and skip it forever, leaving the interpreter
    unable to import the compiled artifact. ABI-aware: the mismatched
    tag must force a real commit even though the version matches."""
    deps_dir = tmp_path / "deps"
    deps_dir.mkdir()
    _make_pkg_dir(deps_dir, "websockets", marker="OLD-ABI")
    (deps_dir / "websockets" / "speedups.cpython-313-darwin.so").write_bytes(b"old")
    _make_dist_info(deps_dir, "websockets", "15.0")

    def fake_run(cmd, **kwargs):
        tmp_dir = Path(cmd[cmd.index("--target") + 1])
        _make_pkg_dir(tmp_dir, "websockets", marker="NEW-ABI")
        (tmp_dir / "websockets" / "speedups.cpython-314-darwin.so").write_bytes(b"new")
        _make_dist_info(tmp_dir, "websockets", "15.0")  # same version as dest

        class _Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return _Result()

    monkeypatch.setattr(
        deps_mod._install._fs,
        "current_extension_abi_suffix",
        lambda: ".cpython-314-darwin.so",
    )
    _route_install(monkeypatch, deps_mod, fake_run)
    ok = deps_mod._install_locked_set(str(deps_dir), _SET)
    assert ok is True
    pkg_dir = deps_dir / "websockets"
    assert (pkg_dir / "speedups.cpython-314-darwin.so").exists()
    assert not (pkg_dir / "speedups.cpython-313-darwin.so").exists()
    assert "NEW-ABI" in (pkg_dir / "__init__.py").read_text(encoding="utf-8")


def test_pip_install_prunes_orphaned_top_level_foreign_abi_extension(
    deps_mod, tmp_path, monkeypatch
):
    """Issue #540, second shape: a `--target` install of a standalone
    C-extension module (cffi's `_cffi_backend`, never wrapped in a
    package dir) leaves the OLD interpreter's file sitting right next
    to the freshly committed one -- distinct top-level names, so the
    commit loop's per-entry logic never revisits the old one. The
    orphan must be pruned once the whole batch has committed."""
    deps_dir = tmp_path / "deps"
    deps_dir.mkdir()
    (deps_dir / "_cffi_backend.cpython-313-darwin.so").write_bytes(b"old")
    _make_dist_info(deps_dir, "cffi", "1.17.1")

    def fake_run(cmd, **kwargs):
        tmp_dir = Path(cmd[cmd.index("--target") + 1])
        tmp_dir.mkdir(parents=True, exist_ok=True)
        (tmp_dir / "_cffi_backend.cpython-314-darwin.so").write_bytes(b"new")
        _make_dist_info(tmp_dir, "cffi", "1.17.1")

        class _Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return _Result()

    monkeypatch.setattr(
        deps_mod._install._fs,
        "current_extension_abi_suffix",
        lambda: ".cpython-314-darwin.so",
    )
    _route_install(monkeypatch, deps_mod, fake_run)
    ok = deps_mod._install_locked_set(str(deps_dir), _SET)
    assert ok is True
    assert (deps_dir / "_cffi_backend.cpython-314-darwin.so").exists()
    assert not (deps_dir / "_cffi_backend.cpython-313-darwin.so").exists()


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

    _route_install(monkeypatch, deps_mod, fake_run)

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

    ok = deps_mod._install_locked_set(str(deps_dir), _SET)

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

    _route_install(monkeypatch, deps_mod, fake_run)

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

    ok = deps_mod._install_locked_set(str(deps_dir), _SET)

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

    _route_install(monkeypatch, deps_mod, fake_run)
    assert deps_mod._install_locked_set(str(deps_dir), _SET) is True
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

    _route_install(monkeypatch, deps_mod, fake_run)
    ok = deps_mod._install_locked_set(str(deps_dir), _SET)
    assert ok is False


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

    _route_install(monkeypatch, deps_mod, fake_run)
    ok = deps_mod._install_locked_set(str(deps_dir), _SET)
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

    _route_install(monkeypatch, deps_mod, fake_run)
    deps_mod._install_locked_set(str(deps_dir), _SET)
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
    _route_install(monkeypatch, deps_mod, fake_run)
    monkeypatch.setattr(
        deps_mod._install._fs,
        "prune_superseded_dist_info",
        lambda *a, **k: pruned.__setitem__("called", True),
    )
    ok = deps_mod._install_locked_set(str(deps_dir), _SET)
    assert ok is True
    assert pruned["called"] is False


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
