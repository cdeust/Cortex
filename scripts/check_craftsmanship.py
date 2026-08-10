"""Craftsmanship gate: a deterministic pass/fail check for the rules
``CLAUDE.md`` § Code Style states but — until this script — nothing
verified. See ``craftsmanship_rules.py`` for what each rule checks and why
its violation identifier is stable; see ``craftsmanship_baseline.py`` for
the ratchet that lets pre-existing debt through without blocking new debt,
and for why the comparison source is the PR's BASE ref, never the working
tree (a working-tree baseline is self-service: add a violation, then run
``--write-baseline`` in the same tree, and the gate would pass on it —
reproduced and closed, see that module's docstring).

Scope: by default, only the files a PR's diff touches (never the whole
repository) — a file untouched by this change is not this change's
problem. ``--write-baseline`` is the one mode that scans everything, because
regenerating the baseline is exactly the operation that must see the whole
tree.

Usage::

    python scripts/check_craftsmanship.py                 # diff vs origin/main
    python scripts/check_craftsmanship.py --base main      # diff vs an explicit ref
    python scripts/check_craftsmanship.py path/to/file.py  # explicit files
    python scripts/check_craftsmanship.py --write-baseline # regenerate the baseline

Exit codes: 0 clean, 1 new/stale/added-without-a-base violations found,
2 could not determine which files to check (git diff failed and no files
were given explicitly) or could not resolve the base ref in diff mode.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)
import craftsmanship_rules as rules  # noqa: E402
import craftsmanship_baseline as baseline_mod  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BASELINE = REPO_ROOT / ".craftsmanship-baseline.json"


def _run_git(args: list[str]) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    return result.stdout


def resolve_base_ref(explicit: str | None) -> str | None:
    """Return the first ref that exists among the explicit ref, the PR's
    base branch (if running under GitHub Actions), and ``origin/main``.
    """
    pr_base = os.environ.get("GITHUB_BASE_REF")
    candidates = [explicit, f"origin/{pr_base}" if pr_base else None, "origin/main"]
    for candidate in candidates:
        if candidate and _run_git(["rev-parse", "--verify", candidate]) is not None:
            return candidate
    return None


def changed_python_files(base_ref: str) -> list[str] | None:
    """Files added/copied/modified/renamed on this branch since ``base_ref``."""
    output = _run_git(
        [
            "diff",
            "--name-only",
            "--diff-filter=ACMR",
            f"{base_ref}...HEAD",
            "--",
            "*.py",
        ]
    )
    if output is None:
        return None
    return sorted(line for line in output.splitlines() if line)


def all_tracked_python_files() -> list[str]:
    """Every git-tracked ``.py`` file — the scope for ``--write-baseline``."""
    output = _run_git(["ls-files", "--", "*.py"]) or ""
    return sorted(line for line in output.splitlines() if line)


def scan_files(rel_paths: list[str]) -> set[rules.Violation]:
    """Scan each path (relative to REPO_ROOT); a missing file yields nothing."""
    found: set[rules.Violation] = set()
    for rel_path in rel_paths:
        full_path = REPO_ROOT / rel_path
        if not full_path.is_file():
            continue
        source = full_path.read_text(encoding="utf-8")
        found.update(rules.scan_source(rel_path, source))
    return found


def _relative_to_repo(path: Path) -> str | None:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return None


def _git_path_exists_at_ref(ref: str, relative_path: str) -> bool:
    try:
        subprocess.run(
            ["git", "cat-file", "-e", f"{ref}:{relative_path}"],
            cwd=REPO_ROOT,
            capture_output=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False
    return True


def load_baseline_from_ref(
    ref: str | None, baseline_path: Path
) -> set[rules.Violation] | None:
    """The baseline exactly as committed at ``ref`` — immutable to the PR's
    own commits, unlike ``baseline_mod.load_baseline`` (working tree).

    Returns None — "nothing to compare against" — when: ``ref`` is None;
    ``baseline_path`` is not inside this repo (e.g. a test's temp dir);
    or the file does not exist at ``ref`` yet (this PR is the one
    introducing it — bootstrap, exempt from the ratchet-file check below).
    A ``git show`` failure AFTER ``cat-file`` confirmed the path exists is
    a different case entirely — a real git error, not "doesn't exist yet"
    — and raises rather than returning None, so it can never be silently
    read as permissive bootstrap.
    """
    if ref is None:
        return None
    relative_path = _relative_to_repo(baseline_path)
    if relative_path is None:
        return None
    if not _git_path_exists_at_ref(ref, relative_path):
        return None
    output = _run_git(["show", f"{ref}:{relative_path}"])
    if output is None:
        raise RuntimeError(
            f"git show {ref}:{relative_path} failed after cat-file confirmed "
            "it exists — refusing to treat this as bootstrap"
        )
    return baseline_mod.parse_baseline_json(output)


def _report(
    new: list[rules.Violation],
    stale: list[rules.Violation],
    added: list[rules.Violation],
) -> None:
    if added:
        print(
            "Craftsmanship gate: baseline entries ADDED without a base-ref "
            "match (the ratchet only shrinks — fix the violation, don't "
            "grandfather it):",
            file=sys.stderr,
        )
        for v in added:
            print(f"  - [{v.kind}] {v.file}: {v.detail}", file=sys.stderr)
    if new:
        print(
            "Craftsmanship gate: NEW violations (not in the base-ref baseline):",
            file=sys.stderr,
        )
        for v in new:
            print(f"  - [{v.kind}] {v.file}: {v.detail}", file=sys.stderr)
    if stale:
        print(
            "Craftsmanship gate: STALE baseline entries "
            "(fixed in code but still listed — prune them):",
            file=sys.stderr,
        )
        for v in stale:
            print(f"  - [{v.kind}] {v.file}: {v.detail}", file=sys.stderr)
    if not new and not stale and not added:
        print("Craftsmanship gate: OK")


def _write_baseline(baseline_path: Path) -> int:
    files = all_tracked_python_files()
    violations = scan_files(files)
    baseline_mod.save_baseline(baseline_path, violations)
    print(f"Wrote {len(violations)} violation(s) to {baseline_path}")
    for kind, count in baseline_mod.count_by_kind(violations).items():
        print(f"  {kind}: {count}")
    return 0


def _run_gate(
    target_files: list[str], baseline_path: Path, base_ref: str | None
) -> int:
    current = scan_files(target_files)
    working_baseline = baseline_mod.load_baseline(baseline_path)
    base_baseline = load_baseline_from_ref(base_ref, baseline_path)

    # The tamper-proof comparison source for "is this violation already
    # known" is the base ref's baseline — falling back to the working
    # tree's only in the bootstrap case (base_baseline is None: no base
    # ref, or the file does not exist at the base ref yet).
    comparison_baseline = (
        base_baseline if base_baseline is not None else working_baseline
    )
    new = baseline_mod.new_violations(current, comparison_baseline)

    added = (
        baseline_mod.added_entries(working_baseline, base_baseline)
        if base_baseline is not None
        else []
    )

    baseline_files = sorted({v.file for v in working_baseline})
    rescanned = {f: scan_files([f]) for f in baseline_files}
    stale = baseline_mod.stale_entries(working_baseline, rescanned)

    _report(new, stale, added)
    return 1 if (new or stale or added) else 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="*", help="explicit files to check")
    parser.add_argument("--base", default=None, help="git ref to diff/compare against")
    parser.add_argument(
        "--baseline", default=str(DEFAULT_BASELINE), help="baseline JSON path"
    )
    parser.add_argument(
        "--write-baseline",
        action="store_true",
        help="regenerate the baseline from the full tree",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    baseline_path = Path(args.baseline)

    if args.write_baseline:
        return _write_baseline(baseline_path)

    if args.files:
        # Ad hoc/local usage: the base ref still feeds the ratchet-file
        # and base-baseline comparisons below when it resolves, but an
        # unresolved ref here is NOT fatal (offline/no-remote local runs
        # stay usable) — it just falls back to bootstrap semantics.
        target_files = args.files
        base_ref = resolve_base_ref(args.base)
    else:
        base_ref = resolve_base_ref(args.base)
        if base_ref is None:
            print(
                "Craftsmanship gate: could not resolve a base ref to diff against",
                file=sys.stderr,
            )
            return 2
        diffed = changed_python_files(base_ref)
        if diffed is None:
            print(
                f"Craftsmanship gate: `git diff` against {base_ref} failed",
                file=sys.stderr,
            )
            return 2
        target_files = diffed

    return _run_gate(target_files, baseline_path, base_ref)


if __name__ == "__main__":
    raise SystemExit(main())
