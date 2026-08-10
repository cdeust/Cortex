"""Craftsmanship gate: a deterministic pass/fail check for the rules
``CLAUDE.md`` § Code Style states but — until this script — nothing
verified. See ``craftsmanship_rules.py`` for what each rule checks and why
its violation identifier is stable; see ``craftsmanship_baseline.py`` for
the ratchet that lets pre-existing debt through without blocking new debt.

Scope: by default, only the files a PR's diff touches (never the whole
repository) — a file untouched by this change is not this change's
problem. ``--write-baseline`` is the one mode that scans everything, because
regenerating the baseline is exactly the operation that must see the whole
tree.

Usage::

    python scripts/check_craftsmanship.py                 # diff vs origin/main
    python scripts/check_craftsmanship.py --base main      # diff vs an explicit ref
    python scripts/check_craftsmanship.py path/to/file.py  # explicit files, no git
    python scripts/check_craftsmanship.py --write-baseline # regenerate the baseline

Exit codes: 0 clean, 1 new or stale violations found, 2 could not determine
which files to check (git diff failed and no files were given explicitly).
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


def _report(new: list[rules.Violation], stale: list[rules.Violation]) -> None:
    if new:
        print(
            "Craftsmanship gate: NEW violations (not in the baseline):", file=sys.stderr
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
    if not new and not stale:
        print("Craftsmanship gate: OK")


def _write_baseline(baseline_path: Path) -> int:
    files = all_tracked_python_files()
    violations = scan_files(files)
    baseline_mod.save_baseline(baseline_path, violations)
    print(f"Wrote {len(violations)} violation(s) to {baseline_path}")
    return 0


def _run_gate(target_files: list[str], baseline_path: Path) -> int:
    current = scan_files(target_files)
    known_baseline = baseline_mod.load_baseline(baseline_path)
    new = baseline_mod.new_violations(current, known_baseline)

    baseline_files = sorted({v.file for v in known_baseline})
    rescanned = {f: scan_files([f]) for f in baseline_files}
    stale = baseline_mod.stale_entries(known_baseline, rescanned)

    _report(new, stale)
    return 1 if (new or stale) else 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "files", nargs="*", help="explicit files to check (skips git diff)"
    )
    parser.add_argument("--base", default=None, help="git ref to diff against")
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
        target_files = args.files
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

    return _run_gate(target_files, baseline_path)


if __name__ == "__main__":
    raise SystemExit(main())
