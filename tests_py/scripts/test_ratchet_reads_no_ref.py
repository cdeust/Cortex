"""The craftsmanship ratchet reads no ref: its baseline is committed in its own tree.

Owner rule 2026-10-29: no gate makes a decision depend on the identity of a hash,
the tip or the content of main. The ratchet (`scripts/check_craftsmanship.py`) once
read its baseline with `git show origin/main:.craftsmanship-baseline.json`, so a pull
request went stale each time main moved. This test fails when a read of a ref, a
`--base` option or one of the removed ref helpers comes back to the ratchet path or
to the workflows that run it. The behaviour itself (a regression is refused, main
moving changes nothing) is proved in `test_check_craftsmanship_exploits.py`.

Companion of `scripts/tests/test_no_main_comparison.py`, which is delivered by render-ci
and is not edited here.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RATCHET_FILES = (
    "scripts/check_craftsmanship.py",
    "scripts/craftsmanship_git.py",
    "scripts/craftsmanship_baseline.py",
)
REF_READ = re.compile(
    r"origin/|--base\b|\bgit show\b|rev-parse|merge-base|GITHUB_BASE_REF"
    r"|load_baseline_from_ref|resolve_base_ref|changed_python_files"
)
BASE_OPTION = re.compile(r"--base\b")


def _text(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


class RatchetReadsNoRefTests(unittest.TestCase):
    def test_ratchet_sources_read_no_ref(self) -> None:
        for name in RATCHET_FILES:
            self.assertIsNone(REF_READ.search(_text(name)), name)

    def test_workflows_run_the_ratchet_without_a_base(self) -> None:
        workflows = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
        self.assertTrue(workflows, "no workflow found: wrong root " + str(ROOT))
        for path in workflows:
            for line in path.read_text(encoding="utf-8").splitlines():
                if "check_craftsmanship.py" in line:
                    self.assertIsNone(BASE_OPTION.search(line), path.name)

    def test_detector_matches_every_removed_form(self) -> None:
        removed = (
            "git show origin/main:.craftsmanship-baseline.json",
            "check_craftsmanship.py --base origin/main",
            "load_baseline_from_ref(",
            "resolve_base_ref(",
            "changed_python_files(",
            "git rev-parse --verify main",
            "git merge-base HEAD main",
            "os.environ['GITHUB_BASE_REF']",
        )
        for form in removed:
            self.assertIsNotNone(REF_READ.search(form), form)


if __name__ == "__main__":
    unittest.main()
