"""scripts/launcher_site.py path filtering — issue #621.

``without_user_site`` decides which ``sys.path`` entries survive the cut,
and ``user_site_dir`` decides whether there is anything to cut at all.
Both are pure enough to drive with a fake ``sys.path`` and a fake
``site.getusersitepackages``, so a Windows-only failure mode is asserted
on macOS and Linux without a Windows torch stack.

The ``isolate_deps`` side of the module, including real ``.pth``
processing, lives in ``test_launcher_site.py``.
"""

from __future__ import annotations

import os

# The launcher_site fixture arrives from tests_py/scripts/conftest.py.


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


def test_without_user_site_drops_directories_under_user_site(launcher_site, tmp_path):
    """`site` processes user site-packages' own .pth files at interpreter
    start, so a pywin32 installed there has already appended its win32 and
    win32/lib subdirectories. Leaving those behind keeps exactly the
    packages this cut exists to displace."""
    user_site = str(tmp_path / "user-site")
    path = [
        "/first",
        os.path.join(user_site, "win32"),
        os.path.join(user_site, "win32", "lib"),
        user_site,
        "/last",
    ]

    assert launcher_site.without_user_site(path, user_site) == ["/first", "/last"]


def test_without_user_site_keeps_a_sibling_with_a_shared_prefix(
    launcher_site, tmp_path
):
    """A prefix test on the raw string would swallow `user-site-extras`."""
    user_site = str(tmp_path / "user-site")
    sibling = str(tmp_path / "user-site-extras")
    path = [sibling, user_site]

    assert launcher_site.without_user_site(path, user_site) == [sibling]


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
