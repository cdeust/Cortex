"""Git helpers shared by the outcome benchmark resolver tests (issue #343).

Each repository is built with an isolated git configuration and fixed dates,
so object hashes are deterministic and no hook, signing or user config of the
machine running the tests leaks in."""

from __future__ import annotations

import os
import subprocess

_ISOLATED_GIT = {
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@t",
    "GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z",
    "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z",
}


def git(repo, *args, stdin=None):
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        input=stdin,
        check=True,
        capture_output=True,
        text=True,
        env={
            **{k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
            **_ISOLATED_GIT,
        },
    ).stdout.strip()


def make_repo(path):
    """Two commits of ``f.txt``; returns ``path``."""
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q")
    for i in range(2):
        (path / "f.txt").write_text(str(i), encoding="utf-8")
        git(path, "add", "f.txt")
        git(path, "commit", "-qm", f"c{i}")
    return path
