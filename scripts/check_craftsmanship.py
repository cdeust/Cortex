"""Craftsmanship gate: a deterministic pass/fail check for the rules
``CLAUDE.md`` § Code Style states but — until this script — nothing
verified. See ``craftsmanship_rules.py`` for what each rule checks and why
its violation identifier is stable; see ``craftsmanship_baseline.py`` for
the ratchet that lets pre-existing debt through without blocking new debt,
and for why the comparison source is the PR's BASE ref, never the working
tree — a working-tree baseline can be tampered with in either direction
(add a violation and self-regenerate; or hand-delete an entry and leave
the violation in place), both reproduced and closed, see that module's
docstring. Git plumbing (resolving the base ref, reading the baseline as
committed there) lives in ``craftsmanship_git.py``.

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

Exit codes: 0 clean, 1 new/stale/added/falsified-removal violations found,
2 could not determine which files to check (git diff failed and no files
were given explicitly) or could not resolve the base ref in diff mode.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)
import craftsmanship_rules as rules  # noqa: E402
import craftsmanship_baseline as baseline_mod  # noqa: E402
import craftsmanship_git  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BASELINE = REPO_ROOT / ".craftsmanship-baseline.json"


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


def _report(
    new: list[rules.Violation],
    stale: list[rules.Violation],
    added: list[rules.Violation],
    falsified: list[rules.Violation],
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
    if falsified:
        print(
            "Craftsmanship gate: baseline entries REMOVED but the violation "
            "still reproduces (a falsified prune — fix the code, or leave "
            "the entry, don't just delete the JSON line):",
            file=sys.stderr,
        )
        for v in falsified:
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
    if not new and not stale and not added and not falsified:
        print("Craftsmanship gate: OK")


def _write_baseline(baseline_path: Path) -> int:
    files = craftsmanship_git.all_tracked_python_files(REPO_ROOT)
    violations = scan_files(files)
    baseline_mod.save_baseline(baseline_path, violations)
    print(f"Wrote {len(violations)} violation(s) to {baseline_path}")
    for kind, count in baseline_mod.count_by_kind(violations).items():
        print(f"  {kind}: {count}")
    return 0


def _added_and_falsified(
    working_baseline: set[rules.Violation], base_baseline: set[rules.Violation] | None
) -> tuple[list[rules.Violation], list[rules.Violation]]:
    """The two base-ref-anchored ratchet checks — skipped (empty) in the
    bootstrap case (no base-ref baseline to compare against yet).
    """
    if base_baseline is None:
        return [], []
    added = baseline_mod.added_entries(working_baseline, base_baseline)
    removed_files = sorted({v.file for v in base_baseline - working_baseline})
    removed_rescanned = {f: scan_files([f]) for f in removed_files}
    falsified = baseline_mod.falsified_removals(
        base_baseline, working_baseline, removed_rescanned
    )
    return added, falsified


def _run_gate(
    target_files: list[str], baseline_path: Path, base_ref: str | None
) -> int:
    current = scan_files(target_files)
    working_baseline = baseline_mod.load_baseline(baseline_path)
    base_baseline = craftsmanship_git.load_baseline_from_ref(
        REPO_ROOT, base_ref, baseline_path
    )

    # The tamper-proof comparison source for "is this violation already
    # known" is the base ref's baseline — falling back to the working
    # tree's only in the bootstrap case (base_baseline is None: no base
    # ref, or the file does not exist at the base ref yet).
    comparison_baseline = (
        base_baseline if base_baseline is not None else working_baseline
    )
    new = baseline_mod.new_violations(current, comparison_baseline)
    added, falsified = _added_and_falsified(working_baseline, base_baseline)

    baseline_files = sorted({v.file for v in working_baseline})
    rescanned = {f: scan_files([f]) for f in baseline_files}
    stale = baseline_mod.stale_entries(working_baseline, rescanned)

    _report(new, stale, added, falsified)
    return 1 if (new or stale or added or falsified) else 0


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
        base_ref = craftsmanship_git.resolve_base_ref(REPO_ROOT, args.base)
    else:
        base_ref = craftsmanship_git.resolve_base_ref(REPO_ROOT, args.base)
        if base_ref is None:
            print(
                "Craftsmanship gate: could not resolve a base ref to diff against",
                file=sys.stderr,
            )
            return 2
        diffed = craftsmanship_git.changed_python_files(REPO_ROOT, base_ref)
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
