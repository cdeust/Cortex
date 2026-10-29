"""Craftsmanship gate: a deterministic pass/fail check for the rules
``docs/agent-guidance.md`` § Code Style states but — until this script — nothing
verified.

Usage::

    python scripts/check_craftsmanship.py                 # every tracked .py file
    python scripts/check_craftsmanship.py path/to/file.py  # explicit files
    python scripts/check_craftsmanship.py --write-baseline # regenerate the baseline

The measure of the working tree must be at most the baseline committed in
that same tree: a violation absent from it is new debt, an entry whose
violation no longer reproduces is stale and must be pruned in the same
diff. No ref is read, so the result does not depend on what any other
branch holds.

Exit codes: 0 clean, 1 new or stale violations found.

source: ADR-0712"""

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
import craftsmanship_decisions  # noqa: E402

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


def _report(new: list[rules.Violation], stale: list[rules.Violation]) -> None:
    if new:
        print(
            "Craftsmanship gate: NEW violations (not in this tree's baseline):",
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
    if not new and not stale:
        print("Craftsmanship gate: OK")


def _write_baseline(baseline_path: Path) -> int:
    files = craftsmanship_git.all_tracked_python_files(REPO_ROOT)
    violations = scan_files(files)
    baseline_mod.save_baseline(baseline_path, violations)
    print(f"Wrote {len(violations)} violation(s) to {baseline_path}")
    for kind, count in baseline_mod.count_by_kind(violations).items():
        print(f"  {kind}: {count}")
    return 0


def _run_gate(target_files: list[str], baseline_path: Path) -> int:
    # Wiki deletion/renaming can invalidate a pointer in an unchanged file.
    sources = craftsmanship_git.all_tracked_python_files(REPO_ROOT)
    decision_errors = craftsmanship_decisions.check_decisions(
        REPO_ROOT, sorted(set(sources + target_files))
    )
    if decision_errors:
        for error in decision_errors:
            print(f"Craftsmanship gate: [decision-integrity] {error}", file=sys.stderr)
        return 1
    current = scan_files(target_files)
    baseline = baseline_mod.load_baseline(baseline_path)
    new = baseline_mod.new_violations(current, baseline)

    baseline_files = sorted({v.file for v in baseline})
    rescanned = {f: scan_files([f]) for f in baseline_files}
    stale = baseline_mod.stale_entries(baseline, rescanned)

    _report(new, stale)
    return 1 if (new or stale) else 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("files", nargs="*", help="explicit files to check")
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

    target_files = args.files or craftsmanship_git.all_tracked_python_files(REPO_ROOT)
    return _run_gate(target_files, baseline_path)


if __name__ == "__main__":
    raise SystemExit(main())
