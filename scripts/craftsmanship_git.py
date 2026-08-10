"""Git plumbing for the craftsmanship gate: resolving the diff base ref,
listing changed/tracked files, and reading the baseline exactly as
committed at a ref — the tamper-proof comparison source
``craftsmanship_baseline.py``'s module docstring explains the need for.

Split out of ``check_craftsmanship.py`` to stay under the 300-line cap
this gate enforces on everything else (self-application).

Every function takes ``repo_root`` explicitly rather than reading a
module-level constant: ``check_craftsmanship.py`` owns the one true
``REPO_ROOT`` (patched by name in tests — ``mock.patch.object(gate,
"REPO_ROOT", ...)``), and passing it through here means that patch keeps
working after the split instead of silently operating on a second,
un-patched copy.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)
import craftsmanship_baseline as baseline_mod  # noqa: E402
from craftsmanship_rules import Violation  # noqa: E402


def _run_git(repo_root: Path, args: list[str]) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    return result.stdout


def resolve_base_ref(repo_root: Path, explicit: str | None) -> str | None:
    """Return the first ref that exists among the explicit ref, the PR's
    base branch (if running under GitHub Actions), and ``origin/main``.
    """
    pr_base = os.environ.get("GITHUB_BASE_REF")
    candidates = [explicit, f"origin/{pr_base}" if pr_base else None, "origin/main"]
    for candidate in candidates:
        if (
            candidate
            and _run_git(repo_root, ["rev-parse", "--verify", candidate]) is not None
        ):
            return candidate
    return None


def changed_python_files(repo_root: Path, base_ref: str) -> list[str] | None:
    """Files added/copied/modified/renamed on this branch since ``base_ref``."""
    output = _run_git(
        repo_root,
        [
            "diff",
            "--name-only",
            "--diff-filter=ACMR",
            f"{base_ref}...HEAD",
            "--",
            "*.py",
        ],
    )
    if output is None:
        return None
    return sorted(line for line in output.splitlines() if line)


def all_tracked_python_files(repo_root: Path) -> list[str]:
    """Every git-tracked ``.py`` file — the scope for ``--write-baseline``."""
    output = _run_git(repo_root, ["ls-files", "--", "*.py"]) or ""
    return sorted(line for line in output.splitlines() if line)


def _relative_to_repo(repo_root: Path, path: Path) -> str | None:
    try:
        return path.resolve().relative_to(repo_root).as_posix()
    except ValueError:
        return None


# Substrings of the exact git stderr for "the ref resolves fine, but this
# path is not present in that tree" (verified against git 2.54.0: "fatal:
# path 'X' does not exist in 'Y'" for a path never committed, "fatal: path
# 'X' exists on disk, but not in 'Y'" for one present locally but untracked
# at that ref). Anything else — "invalid object name", a crash, permission
# denial — is a REAL git failure, not "doesn't exist yet", and must raise.
_PATH_ABSENT_MARKERS = ("does not exist in", "exists on disk, but not in")


def _git_path_exists_at_ref(repo_root: Path, ref: str, relative_path: str) -> bool:
    """True if ``relative_path`` exists in the tree ``ref`` resolves to.

    Self-audited after the two review-round findings that shared one root
    cause (a control that fails OPEN when a signal is ambiguous, instead
    of failing closed): swallowing every ``cat-file -e`` failure into a
    bare False previously read an unrelated git error (corrupt object, a
    ref that stopped resolving between the caller's earlier
    ``rev-parse --verify`` and this call, disk failure) the exact same way
    it read a genuinely absent path — silently handing
    ``load_baseline_from_ref`` a bootstrap fallback to the tamperable
    working-tree baseline. Distinguishes the two via git's own stderr.
    """
    result = subprocess.run(
        ["git", "cat-file", "-e", f"{ref}:{relative_path}"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return True
    if any(marker in result.stderr for marker in _PATH_ABSENT_MARKERS):
        return False
    raise RuntimeError(
        f"git cat-file -e {ref}:{relative_path} failed unexpectedly "
        f"(exit {result.returncode}): {result.stderr.strip()!r} — refusing "
        f"to treat this as 'path absent, safe to bootstrap'"
    )


def load_baseline_from_ref(
    repo_root: Path, ref: str | None, baseline_path: Path
) -> set[Violation] | None:
    """The baseline exactly as committed at ``ref`` — immutable to the PR's
    own commits, unlike ``baseline_mod.load_baseline`` (working tree).

    Returns None — "nothing to compare against" — when: ``ref`` is None;
    ``baseline_path`` is not inside this repo (e.g. a test's temp dir);
    or the file does not exist at ``ref`` yet (this PR is the one
    introducing it — bootstrap, exempt from the ratchet checks). A
    ``git show`` failure AFTER ``cat-file`` confirmed the path exists is a
    different case entirely — a real git error, not "doesn't exist yet" —
    and raises rather than returning None, so it can never be silently
    read as permissive bootstrap.
    """
    if ref is None:
        return None
    relative_path = _relative_to_repo(repo_root, baseline_path)
    if relative_path is None:
        return None
    if not _git_path_exists_at_ref(repo_root, ref, relative_path):
        return None
    output = _run_git(repo_root, ["show", f"{ref}:{relative_path}"])
    if output is None:
        raise RuntimeError(
            f"git show {ref}:{relative_path} failed after cat-file confirmed "
            "it exists — refusing to treat this as bootstrap"
        )
    return baseline_mod.parse_baseline_json(output)
