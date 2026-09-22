"""install-plugin.sh must name the check scripts/setup.py actually failed.

Source: issue #621, secondary finding. A Windows run whose four
PostgreSQL checks all passed and whose only failing verification row was
``sentence-transformers`` still ended with "PostgreSQL must be installed
and running first" — the installer pointed the reader at a working
component and hid the one that failed.

These tests source the real scripts/lib/setup_py_step.sh and drive it
against a stub command that replays the exact verification block the issue
reports, colour codes included. No pip, no PostgreSQL, no model download.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
LIB_PATH = REPO_ROOT / "scripts" / "lib" / "setup_py_step.sh"
INSTALLER_PATH = REPO_ROOT / "scripts" / "install-plugin.sh"

# The reporter's verification block, verbatim, with setup.py's real colour
# codes around each label (scripts/setup.py ok()/fail()).
_REPORTED_OUTPUT = (
    "  \\033[0;32m[ok]\\033[0m PostgreSQL connection\\n"
    "  \\033[0;32m[ok]\\033[0m Extensions (pgvector, pg_trgm)\\n"
    "  \\033[0;32m[ok]\\033[0m PL/pgSQL recall_memories()\\n"
    "  \\033[0;31m[FAIL]\\033[0m sentence-transformers\\n"
    "  \\033[0;32m[ok]\\033[0m FlashRank reranker\\n"
    "\\033[0;31m[FAIL]\\033[0m Some checks failed \\u2014 see above\\n"
)

_HARNESS = """
set -euo pipefail
source "{lib_path}"
stub() {{
    printf '{output}'
    exit {exit_code}
}}
run_setup_py stub || true
echo "SETUP_PY_FAILURE=${{SETUP_PY_FAILURE}}"
"""

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None, reason="bash is required to drive the shell library"
)


def _drive(output: str, exit_code: int) -> str:
    script = _HARNESS.format(lib_path=LIB_PATH, output=output, exit_code=exit_code)
    result = subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def _failure_line(stdout: str) -> str:
    for line in stdout.splitlines():
        if line.startswith("SETUP_PY_FAILURE="):
            return line[len("SETUP_PY_FAILURE=") :]
    raise AssertionError(f"harness never printed SETUP_PY_FAILURE:\n{stdout}")


def test_reported_run_names_sentence_transformers_not_postgresql():
    failure = _failure_line(_drive(_REPORTED_OUTPUT, 1))

    assert "sentence-transformers" in failure
    assert "PostgreSQL" not in failure
    # The "Some checks failed" summary names no check — quoting it back
    # would be the same unhelpful message in a new wrapper.
    assert "Some checks failed" not in failure


def test_every_failed_check_is_listed():
    output = (
        "  \\033[0;31m[FAIL]\\033[0m sentence-transformers\\n"
        "  \\033[0;31m[FAIL]\\033[0m FlashRank reranker\\n"
    )

    failure = _failure_line(_drive(output, 1))

    assert "sentence-transformers" in failure
    assert "FlashRank reranker" in failure


def test_a_real_postgresql_failure_is_still_named():
    output = "  \\033[0;31m[FAIL]\\033[0m PostgreSQL connection\\n"

    failure = _failure_line(_drive(output, 1))

    assert "PostgreSQL connection" in failure


def test_a_run_that_reports_no_check_says_so_instead_of_guessing():
    failure = _failure_line(_drive("Traceback (most recent call last)\\n", 1))

    assert "PostgreSQL" not in failure
    assert "exited before reporting any check" in failure


def test_a_successful_run_leaves_no_failure_sentence():
    failure = _failure_line(_drive("  \\033[0;32m[ok]\\033[0m everything\\n", 0))

    assert failure == ""


def test_installer_no_longer_asserts_postgresql_is_the_cause():
    """The unconditional claim is gone from both setup.py call sites; the
    PostgreSQL install guidance survives as a conditional."""
    installer = INSTALLER_PATH.read_text(encoding="utf-8")

    assert "PostgreSQL must be installed and running first" not in installer
    invocations = [
        line
        for line in installer.splitlines()
        if line.strip().startswith("run_setup_py ")
    ]
    assert len(invocations) == 2, "both the SQLite and the Windows call sites"
    assert installer.count("${SETUP_PY_FAILURE}") == 2
