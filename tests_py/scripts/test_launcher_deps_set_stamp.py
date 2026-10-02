"""scripts/launcher_deps.py: a set is reinstalled only when uv.lock changes IT.

uv.lock changes on every dependency bump, most of them outside the two sets
the launcher installs; the stamp also records the digest of the exported set,
so such a change restamps without downloading anything.

source: ADR-1092"""

from __future__ import annotations

import sys

from tests_py.scripts import test_launcher_deps_lock as _lock

# The same fixtures, bound by assignment: importing them by name would make
# every test parameter below read as a redefinition (ruff F811).
deps_mod, deps_dir, calls = _lock.deps_mod, _lock.deps_dir, _lock.calls
DIGEST, SET, _stamp = _lock.DIGEST, _lock.SET, _lock._stamp

OLD_LOCK = "0" * 64


def test_a_lock_change_outside_the_set_restamps_without_installing(
    deps_mod, deps_dir, calls
):
    """A dev-tool bump rewrites uv.lock; the user's installed set is unchanged."""
    deps_mod._write_stamp(str(deps_dir), "base", OLD_LOCK, SET)
    deps_mod.ensure_deps(str(deps_dir))
    assert calls == []
    assert _stamp(deps_mod, deps_dir, "base") == {
        "python": f"{sys.version_info.major}.{sys.version_info.minor}",
        "lock": DIGEST,
        "set": SET,
    }


def test_the_set_digest_is_read_for_this_deps_dir_and_set(
    deps_mod, deps_dir, calls, monkeypatch
):
    asked = []
    monkeypatch.setattr(
        deps_mod, "_locked_set_digest", lambda *a: asked.append(a) or SET
    )
    deps_mod.ensure_deps(str(deps_dir))
    assert asked == [(str(deps_dir), ("--only-group", "launcher-base"))]


def test_a_changed_set_is_installed_again(deps_mod, deps_dir, calls):
    deps_mod._write_stamp(str(deps_dir), "base", OLD_LOCK, "6" * 64)
    deps_mod.ensure_deps(str(deps_dir))
    assert calls == [(str(deps_dir), ("--only-group", "launcher-base"))]
    assert _stamp(deps_mod, deps_dir, "base")["set"] == SET


def test_an_unchanged_set_that_no_longer_imports_is_installed_again(
    deps_mod, deps_dir, calls, monkeypatch
):
    deps_mod._write_stamp(str(deps_dir), "base", OLD_LOCK, SET)
    answers = iter([False] + [True] * len(deps_mod._sets.BASE_IMPORTS))
    monkeypatch.setattr(deps_mod, "_importable", lambda *_a: next(answers))
    deps_mod.ensure_deps(str(deps_dir))
    assert calls == [(str(deps_dir), ("--only-group", "launcher-base"))]
    assert _stamp(deps_mod, deps_dir, "base")["lock"] == DIGEST


def test_an_unreadable_set_installs_nothing_and_keeps_the_old_stamp(
    deps_mod, deps_dir, calls, monkeypatch
):
    deps_mod._write_stamp(str(deps_dir), "base", OLD_LOCK, SET)
    monkeypatch.setattr(deps_mod, "_locked_set_digest", lambda *_a: None)
    deps_mod.ensure_deps(str(deps_dir))
    assert calls == []
    assert _stamp(deps_mod, deps_dir, "base")["lock"] == OLD_LOCK
