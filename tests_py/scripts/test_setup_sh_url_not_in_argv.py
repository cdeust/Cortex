"""scripts/setup.sh keeps the database URL out of process arguments.

The verification step used to expand ``'${DATABASE_URL}'`` into a
``python3 -c`` argument, and the summary echoed the URL as is: a password in
the URL was readable by every local user (argv) and printed to the install
log. Codex security review of #1029; SECURITY.md.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SETUP_SH = REPO_ROOT / "scripts" / "setup.sh"
# A ``python3 -c "`` block runs to the next line that is a lone ``"``.
_PY_BLOCK = re.compile(r'python3 -c "\n(.*?)\n"', re.DOTALL)
_SECRET = "s3cr3t-pw"


def _python_blocks() -> list[str]:
    return _PY_BLOCK.findall(SETUP_SH.read_text(encoding="utf-8"))


def test_no_python_block_expands_the_database_url():
    blocks = _python_blocks()
    assert blocks, "setup.sh has python3 -c blocks to check"
    for block in blocks:
        assert "${DATABASE_URL" not in block and "$DATABASE_URL" not in block


def test_the_summary_prints_the_url_with_its_password_masked():
    summary = [b for b in _python_blocks() if "Database: " in b]
    assert len(summary) == 1
    env = dict(
        os.environ,
        PYTHONPATH=str(REPO_ROOT),
        DATABASE_URL=f"postgresql://cortex:{_SECRET}@db.example:5432/cortex",
    )
    result = subprocess.run(
        [sys.executable, "-c", summary[0]],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    assert _SECRET not in result.stdout + result.stderr
    assert "Database: postgresql://cortex:***@db.example:5432/cortex" in result.stdout
