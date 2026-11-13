"""The install scripts keep the database URL out of process arguments.

``scripts/setup.sh`` used to expand ``'${DATABASE_URL}'`` into a
``python3 -c`` argument, and its summary echoed the URL as is; the Docker
entrypoint expanded it the same way into its schema step. A password in the
URL was then readable by every local user (argv), printed to the install log,
and a quote in it broke the code. Codex security review of #1029, review of
#1030; the rule is the one the managed server already follows (source:
scripts/launcher_pg_provision.py:10, "the password never reaches argv"), and
the summary masks with ``redact_url`` (source: ADR-0663).
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SETUP_SH = REPO_ROOT / "scripts" / "setup.sh"
ENTRYPOINT_SH = REPO_ROOT / "docker" / "entrypoint.sh"
# Any shell expansion: $DATABASE_URL, ${DATABASE_URL}, ${DATABASE_URL:-…}.
_EXPANSION = re.compile(r"\$\{?DATABASE_URL\b")
# The one expansion allowed: setup.sh exports its default before the steps
# that read the URL from the environment.
_EXPORT_LINE = (
    'export DATABASE_URL="${DATABASE_URL:-postgresql://127.0.0.1:5432/cortex}"'
)
# A ``python3 -c "`` block runs to the next line that is a lone ``"``.
_PY_BLOCK = re.compile(r'python3 -c "\n(.*?)\n"', re.DOTALL)
_SECRET = "s3cr3t-pw"


def _expansions(script: Path) -> list[str]:
    lines = script.read_text(encoding="utf-8").splitlines()
    return [
        f"{script.name}:{number}: {line.strip()}"
        for number, line in enumerate(lines, start=1)
        if _EXPANSION.search(line) and line.strip() != _EXPORT_LINE
    ]


def _python_blocks(script: Path) -> list[str]:
    return _PY_BLOCK.findall(script.read_text(encoding="utf-8"))


def test_setup_sh_expands_the_database_url_only_in_its_export_line():
    assert _EXPORT_LINE in SETUP_SH.read_text(encoding="utf-8")
    assert _expansions(SETUP_SH) == []


def test_the_docker_entrypoint_never_expands_the_database_url():
    assert _expansions(ENTRYPOINT_SH) == []


def test_the_scan_sees_every_form_of_expansion(tmp_path: Path):
    script = tmp_path / "probe.sh"
    script.write_text(
        "\n".join(
            [
                _EXPORT_LINE,
                "python3 -c \"import psycopg; psycopg.connect('$DATABASE_URL')\"",
                'psql "${DATABASE_URL}" -c "SELECT 1"',
                'echo "Database: ${DATABASE_URL:-none}"',
                "# DATABASE_URL is read from the environment",
            ]
        ),
        encoding="utf-8",
    )
    assert [entry.split(":")[1] for entry in _expansions(script)] == ["2", "3", "4"]


def test_the_summary_prints_the_url_with_its_password_masked():
    summary = [b for b in _python_blocks(SETUP_SH) if "Database: " in b]
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
