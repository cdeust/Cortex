"""The tracked tree carries no raw benchmark stdout of BEAM-10M and no video media.

The plugin tree is the repository (the marketplace source is ``./``,
ADR-1108 fact 6), so every tracked file is installed on every machine. Issue
#705 measured 72 MB under ``benchmarks/`` and 17 MB under ``video/``: five
BEAM-10M variance runs and one oracle log of about 11.7 MB each, and the
frames and render of ``video/generate.py``. The sdist already excluded them
(ADR-0874). This test keeps them out of the tree and keeps ``.gitignore``
refusing a new one.

source: issue #705 ("The plugin tree ships no benchmark data or media"),
ADR-0874 (sdist exclusions), ADR-1108
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
# The paths issue #705 removed; each one stays readable at this commit.
# source: issue #705, measured on main at 1bfbc459
REMOVED_AT = "1bfbc459"
REMOVED_PREFIXES = (
    "benchmarks/beam/variance/assembler_10m",
    "benchmarks/beam/variance/baseline_10m",
    "benchmarks/results/beam10m_paired/20260611-oracle-currentcode.log",
    "video/captures/",
    "video/output/",
)
# A new file each pattern of .gitignore must refuse.
# source: .gitignore entries added for issue #705, and benchmarks/results/**/*.log
IGNORED_EXAMPLES = (
    "benchmarks/beam/variance/assembler_10m_run1.txt",
    "benchmarks/results/beam10m_paired/next-run.log",
    "video/captures/frame.png",
    "video/output/cortex_memory.mp4",
)


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=False
    )


def test_no_removed_path_is_tracked():
    tracked = _git("ls-files").stdout.splitlines()
    assert tracked, "git ls-files returned nothing"
    back = [p for p in tracked if p.startswith(REMOVED_PREFIXES)]
    assert back == [], back


@pytest.mark.parametrize("path", IGNORED_EXAMPLES)
def test_gitignore_refuses_a_new_one(path):
    result = _git("check-ignore", "--no-index", "-q", path)
    assert result.returncode == 0, f"{path} is not ignored"


def test_variance_readme_names_the_commit_that_still_holds_them():
    readme = REPO_ROOT / "benchmarks" / "beam" / "variance" / "README.md"
    assert f"git show {REMOVED_AT}:" in readme.read_text(encoding="utf-8")
