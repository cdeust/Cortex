"""scripts/launcher_site.py — deps/ isolation from user site-packages.

Source: issue #621. On a Windows machine whose user site-packages holds a
coherent CUDA torch/torchvision/torchaudio set, the plugin's vendored
``deps/`` (CPU torch, no torchvision) was merely first on ``sys.path``.
``torch`` then came from ``deps/`` and ``torchvision`` from user
site-packages, built against the other torch, and importing them together
aborted the MCP server during startup. The reporter's first workaround —
cutting user site-packages alone — moved the failure to ``pywintypes``,
because ``deps/pywin32.pth`` is only processed for a *site* directory, not
for one added with ``sys.path.insert``.

Both halves are asserted here without a Windows torch stack: the logic
under test is which entries ``sys.path`` ends up carrying and whether a
``.pth`` file in the deps directory is processed. ``site.addsitedir``'s
``.pth`` handling is identical on every platform, so a temporary deps
directory holding a real ``.pth`` file exercises it for real on macOS and
Linux too.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "scripts" / "launcher_site.py"


@pytest.fixture
def launcher_site():
    """Load scripts/launcher_site.py under its path-derived dotted name.

    "scripts.launcher_site" is the name mutmut derives from the file's
    location; a synthetic name makes every mutant look unreached (#262).
    """
    spec = importlib.util.spec_from_file_location("scripts.launcher_site", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_without_user_site_drops_the_matching_entry(launcher_site, tmp_path):
    user_site = str(tmp_path / "user-site")
    path = ["/first", user_site, "/last"]

    assert launcher_site.without_user_site(path, user_site) == ["/first", "/last"]


def test_without_user_site_drops_an_unnormalized_spelling(launcher_site, tmp_path):
    """The same directory reaches sys.path spelled differently than `site`
    reports it — a trailing separator, or a `.` segment. Comparing raw
    strings would keep it, and keeping it is what breaks the import."""
    user_site = str(tmp_path / "user-site")
    trailing = user_site + os.sep
    dotted = os.path.join(str(tmp_path), ".", "user-site")
    path = ["/first", trailing, dotted, "/last"]

    assert launcher_site.without_user_site(path, user_site) == ["/first", "/last"]


def test_without_user_site_preserves_order_and_duplicates(launcher_site):
    path = ["/a", "/b", "/a", "/c"]

    assert launcher_site.without_user_site(path, None) == ["/a", "/b", "/a", "/c"]
    assert launcher_site.without_user_site(path, "") == ["/a", "/b", "/a", "/c"]


def test_without_user_site_returns_a_new_list(launcher_site):
    path = ["/a"]

    assert launcher_site.without_user_site(path, None) is not path


def test_user_site_dir_never_raises(launcher_site, monkeypatch, capsys):
    """A launch must survive a sysconfig that cannot resolve the user base
    — and must say so. Returning None leaves user site-packages on
    sys.path, which is issue #621's symptom exactly, so swallowing the
    cause would make the bug recur with no trace at all."""
    monkeypatch.setattr(
        launcher_site.site,
        "getusersitepackages",
        lambda: (_ for _ in ()).throw(KeyError("userbase")),
    )

    assert launcher_site.user_site_dir() is None

    reported = capsys.readouterr().err
    assert "userbase" in reported, "the cause must reach stderr, not be swallowed"
    assert "not isolated" in reported, "and say what it costs the caller"


def test_user_site_dir_stays_quiet_when_it_resolves(launcher_site, monkeypatch, capsys):
    """Every hook launch calls this; a diagnostic on the normal path would
    be noise in eleven hooks' stderr."""
    monkeypatch.setattr(
        launcher_site.site, "getusersitepackages", lambda: "/fake/user/site"
    )

    launcher_site.user_site_dir()

    assert capsys.readouterr().err == ""


def test_user_site_dir_reports_what_site_reports(launcher_site, monkeypatch):
    monkeypatch.setattr(
        launcher_site.site, "getusersitepackages", lambda: "/fake/user/site"
    )

    assert launcher_site.user_site_dir() == "/fake/user/site"


def _deps_dir_with_pth(tmp_path: Path, marker: Path, probe_name: str) -> Path:
    """A deps directory shaped like the plugin's: a .pth naming a nested
    package directory and importing a bootstrap module, exactly as
    deps/pywin32.pth does for win32/win32\\lib/pythonwin."""
    deps = tmp_path / "deps"
    (deps / "win32" / "lib").mkdir(parents=True)
    (deps / f"{probe_name}.py").write_text(
        f"import pathlib\npathlib.Path({str(marker)!r}).write_text('ran')\n",
        encoding="utf-8",
    )
    (deps / "vendored.pth").write_text(
        f"win32\nwin32{os.sep}lib\nimport {probe_name}\n", encoding="utf-8"
    )
    return deps


def test_isolate_deps_processes_pth_files_and_cuts_user_site(
    launcher_site, tmp_path, monkeypatch
):
    """The whole contract in one run: the .pth's directories become
    importable, its `import` line executes, and the user site-packages
    entry is gone — while deps/ keeps the position the caller gave it."""
    marker = tmp_path / "pth-ran.txt"
    probe_name = "_cortex_pth_probe_621"
    deps = _deps_dir_with_pth(tmp_path, marker, probe_name)
    user_site = str(tmp_path / "user-site")

    monkeypatch.setattr(launcher_site.site, "getusersitepackages", lambda: user_site)
    monkeypatch.setattr(sys, "path", [str(deps), "/plugin/root", user_site, "/stdlib"])
    monkeypatch.delitem(sys.modules, probe_name, raising=False)

    launcher_site.isolate_deps(str(deps))

    assert sys.path[0] == str(deps), "deps/ must keep the caller's precedence"
    assert user_site not in sys.path
    assert str(deps / "win32") in sys.path
    assert str(deps / "win32" / "lib") in sys.path
    assert marker.read_text(encoding="utf-8") == "ran"

    sys.modules.pop(probe_name, None)


def test_isolate_deps_does_not_duplicate_the_deps_entry(
    launcher_site, tmp_path, monkeypatch
):
    deps = tmp_path / "deps"
    deps.mkdir()
    monkeypatch.setattr(launcher_site.site, "getusersitepackages", lambda: None)
    monkeypatch.setattr(sys, "path", [str(deps), "/stdlib"])

    launcher_site.isolate_deps(str(deps))

    assert sys.path.count(str(deps)) == 1


def test_isolate_deps_tolerates_a_deps_dir_that_does_not_exist(
    launcher_site, tmp_path, monkeypatch
):
    """The first launch after an update can reach this before the
    directory is created; it must not raise."""
    deps = tmp_path / "not-created-yet"
    user_site = str(tmp_path / "user-site")
    monkeypatch.setattr(launcher_site.site, "getusersitepackages", lambda: user_site)
    monkeypatch.setattr(sys, "path", ["/plugin/root", user_site])

    launcher_site.isolate_deps(str(deps))

    assert user_site not in sys.path


def test_isolate_deps_puts_an_absent_deps_dir_first(
    launcher_site, tmp_path, monkeypatch
):
    """isolate_deps owns the insert, so no call site can get the order
    wrong. site.addsitedir alone would APPEND deps/, landing it behind
    system site-packages — the position that loses the whole fix."""
    marker = tmp_path / "pth-ran.txt"
    probe_name = "_cortex_pth_probe_621_absent"
    deps = _deps_dir_with_pth(tmp_path, marker, probe_name)
    monkeypatch.setattr(launcher_site.site, "getusersitepackages", lambda: None)
    monkeypatch.setattr(sys, "path", ["/stdlib", "/system/site-packages"])
    monkeypatch.delitem(sys.modules, probe_name, raising=False)

    launcher_site.isolate_deps(str(deps))

    assert sys.path[0] == str(deps)
    assert sys.path.index(str(deps)) < sys.path.index("/system/site-packages")

    sys.modules.pop(probe_name, None)


def test_isolate_deps_picks_up_a_pth_that_arrived_since_the_last_call(
    launcher_site, tmp_path, monkeypatch
):
    """scripts/launcher.py calls isolate_deps once before ensure_deps and
    once after, because that install can land a .pth the first call could
    not see. A .pth left unprocessed is issue #621's bug class again."""
    deps = tmp_path / "deps"
    deps.mkdir()
    monkeypatch.setattr(launcher_site.site, "getusersitepackages", lambda: None)
    monkeypatch.setattr(sys, "path", ["/stdlib"])

    launcher_site.isolate_deps(str(deps))
    assert str(deps / "late") not in sys.path

    # What ensure_deps/ensure_all_deps does between the two calls.
    (deps / "late").mkdir()
    (deps / "late.pth").write_text("late\n", encoding="utf-8")

    launcher_site.isolate_deps(str(deps))

    assert str(deps / "late") in sys.path
    assert sys.path.count(str(deps)) == 1, "the repeat must not duplicate deps/"


def test_isolate_deps_is_idempotent(launcher_site, tmp_path, monkeypatch):
    marker = tmp_path / "pth-ran.txt"
    probe_name = "_cortex_pth_probe_621_twice"
    deps = _deps_dir_with_pth(tmp_path, marker, probe_name)
    user_site = str(tmp_path / "user-site")
    monkeypatch.setattr(launcher_site.site, "getusersitepackages", lambda: user_site)
    monkeypatch.setattr(sys, "path", [user_site, "/stdlib"])
    monkeypatch.delitem(sys.modules, probe_name, raising=False)

    launcher_site.isolate_deps(str(deps))
    after_first = list(sys.path)
    launcher_site.isolate_deps(str(deps))

    assert sys.path == after_first
    assert user_site not in sys.path

    sys.modules.pop(probe_name, None)


def test_launcher_reisolates_after_installing_dependencies():
    """The second call must come after ensure_deps/ensure_all_deps, or the
    .pth files that install writes stay inert until the next launch."""
    source = (REPO_ROOT / "scripts" / "launcher.py").read_text(encoding="utf-8")
    isolate_calls = [
        index
        for index, line in enumerate(source.splitlines())
        if "launcher_site.isolate_deps(deps_dir)" in line
    ]
    ensure_at = next(
        index
        for index, line in enumerate(source.splitlines())
        if "launcher_deps.ensure_deps(deps_dir)" in line
    )

    assert len(isolate_calls) == 2, "once before the install, once after"
    assert isolate_calls[0] < ensure_at < isolate_calls[1]


def test_launcher_puts_deps_on_sys_path_only_through_isolate_deps():
    """scripts/launcher.py must not re-add deps_dir itself: a bare insert
    beside the isolating one is how the two drift apart. plugin_root is
    still inserted directly — it carries no .pth files and no vendored
    distributions."""
    source = (REPO_ROOT / "scripts" / "launcher.py").read_text(encoding="utf-8")

    assert "launcher_site.isolate_deps(deps_dir)" in source
    assert "sys.path.insert(0, deps_dir)" not in source
    assert "for p in [plugin_root, deps_dir]" not in source


def test_setup_py_verifies_through_isolate_deps():
    """scripts/setup.py's verification must check what the plugin will
    actually import — a bare insert there reproduces the reported
    [FAIL] sentence-transformers row."""
    source = (REPO_ROOT / "scripts" / "setup.py").read_text(encoding="utf-8")

    assert "launcher_site.isolate_deps(DEPS_DIR)" in source
    assert "sys.path.insert(0, DEPS_DIR)\n    # source: ADR-0782" not in source
