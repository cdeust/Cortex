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


def test_user_site_dir_never_raises(launcher_site, monkeypatch):
    """A launch must survive a sysconfig that cannot resolve the user base."""
    monkeypatch.setattr(
        launcher_site.site,
        "getusersitepackages",
        lambda: (_ for _ in ()).throw(KeyError("userbase")),
    )

    assert launcher_site.user_site_dir() is None


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


def test_launcher_isolates_after_inserting_deps():
    """scripts/launcher.py must call isolate_deps with the deps directory
    it just put on sys.path — the seam shared by the MCP server and all
    eleven lifecycle hooks (ADR-0742)."""
    source = (REPO_ROOT / "scripts" / "launcher.py").read_text(encoding="utf-8")
    insert_at = source.index("sys.path.insert(0, p)")
    isolate_at = source.index("launcher_site.isolate_deps(deps_dir)")

    assert insert_at < isolate_at, (
        "isolate_deps must run after deps_dir is on sys.path, so "
        "site.addsitedir keeps its position instead of appending it"
    )
