"""Permanent guard: no CI check may compare a PR's workflow with main's.

Owner rule 2026-10-29: "je veux plus la revoir A VIE". The check that compared
the pipeline.yml executed by a pull request with the one on main (and refused the
autonomous merge with "workflow proof definition is not trusted") was removed. Any
reintroduction under any of the markers below, in .github/workflows/ or scripts/,
fails this test. This file is excluded from its own scan.
"""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SELF = Path(__file__).resolve()
SCANNED = (".github/workflows", "scripts")
FORBIDDEN = (
    "authorize_workflow",
    "workflow proof definition",
    "WORKFLOW_PROOF",
    "ci_workflow_proof",
    "workflow_pr_perime",
    "update-branch",
    "update_branch",
    "merge-base HEAD origin/main",
)
PATTERN = re.compile("|".join(re.escape(m) for m in FORBIDDEN), re.IGNORECASE)
SKIP_DIRS = {"__pycache__", ".git", "node_modules", ".venv"}


def _candidate_files(base: Path, skip: Path | None):
    for path in sorted(base.rglob("*")):
        if not path.is_file() or SKIP_DIRS & set(path.parts):
            continue
        if skip is not None and path.resolve() == skip:
            continue
        yield path


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return ""


def _file_hits(path: Path, root: Path) -> list[str]:
    hits = []
    for number, line in enumerate(_read_text(path).splitlines(), 1):
        match = PATTERN.search(line)
        if match:
            hits.append(f"{path.relative_to(root)}:{number}: {match.group(0)}")
    return hits


def find_violations(root: Path, scanned=SCANNED, skip: Path | None = SELF) -> list[str]:
    hits: list[str] = []
    for rel in scanned:
        base = root / rel
        if base.is_dir():
            for path in _candidate_files(base, skip):
                hits.extend(_file_hits(path, root))
    return hits


class NoMainComparisonTests(unittest.TestCase):
    def test_repository_has_no_comparison_against_main(self) -> None:
        self.assertTrue((ROOT / ".github" / "workflows").is_dir(), "wrong root: " + str(ROOT))
        self.assertEqual(find_violations(ROOT), [])

    def test_guard_detects_every_forbidden_marker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workflows = Path(tmp) / ".github" / "workflows"
            workflows.mkdir(parents=True)
            for index, marker in enumerate(FORBIDDEN):
                (workflows / f"w{index}.yml").write_text(f"run: {marker}\n", encoding="utf-8")
            hits = find_violations(Path(tmp), skip=None)
            self.assertEqual(len(hits), len(FORBIDDEN), hits)


if __name__ == "__main__":
    unittest.main()
