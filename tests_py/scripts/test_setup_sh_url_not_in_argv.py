"""The install scripts keep the database URL and the OAuth token out of argv.

``scripts/setup.sh`` used to expand ``'${DATABASE_URL}'`` into a
``python3 -c`` argument, and its summary echoed the URL as is; the Docker
entrypoint expanded it the same way into its schema step. A password in the
URL was then readable by every local user (argv), printed to the install log,
and a quote in it broke the code. Codex security review of #1029, review of
#1030; the entrypoint also gave ``CLAUDE_CODE_OAUTH_TOKEN`` to ``python3 -c``
as ``sys.argv[1]`` (review of #1031). The rule is the one the managed server
follows (source: ADR-1114 decision 4, "the password never reaches argv"), and
the summary masks with ``redact_url`` (source: ADR-0663).
"""

from __future__ import annotations

import json
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
# The expansions allowed, both shell builtins (no process, no argv): setup.sh
# exports its default before the steps that read the URL from the
# environment, and the entrypoint fails its start when the URL is missing.
_EXPORT_LINE = (
    'export DATABASE_URL="${DATABASE_URL:-postgresql://127.0.0.1:5432/cortex}"'
)
_GUARD_LINE = ': "${DATABASE_URL:?DATABASE_URL is not set (docker/Dockerfile sets it)}"'
_ALLOWED_URL_LINES = frozenset({_EXPORT_LINE, _GUARD_LINE})
_TOKEN_EXPANSION = re.compile(r"\$\{?CLAUDE_CODE_OAUTH_TOKEN\b")
# The token may be expanded only on these exact lines, where it is an operand
# of a builtin (``[[ … ]]``, ``echo``) that runs in the shell itself, so the
# value never reaches an argv. Any edit to one of them fails the scan.
_ALLOWED_TOKEN_LINES = frozenset(
    {
        'if [[ -n "${CLAUDE_CODE_OAUTH_TOKEN:-}"'
        ' && ! -f "$CLAUDE_HOME/.credentials.json" ]]; then',
        'if echo "$CLAUDE_CODE_OAUTH_TOKEN"'
        ' | python3 -c "import sys,json; json.load(sys.stdin)" 2>/dev/null; then',
        'echo "$CLAUDE_CODE_OAUTH_TOKEN" > "$CLAUDE_HOME/.credentials.json"',
        'if [[ ! -f "$CLAUDE_HOME/.credentials.json"'
        ' && -z "${ANTHROPIC_API_KEY:-}"'
        ' && -z "${CLAUDE_CODE_OAUTH_TOKEN:-}" ]]; then',
    }
)
# A ``python3 -c "`` block runs to the next line that is a lone ``"``.
_PY_BLOCK = re.compile(r'python3 -c "\n(.*?)\n"', re.DOTALL)
_SECRET = "s3cr3t-pw"


def _expansions(script: Path) -> list[str]:
    lines = script.read_text(encoding="utf-8").splitlines()
    return [
        f"{script.name}:{number}: {line.strip()}"
        for number, line in enumerate(lines, start=1)
        if _EXPANSION.search(line) and line.strip() not in _ALLOWED_URL_LINES
    ]


def _token_outside_builtins(script: Path) -> list[str]:
    lines = script.read_text(encoding="utf-8").splitlines()
    return [
        f"{script.name}:{number}: {line.strip()}"
        for number, line in enumerate(lines, start=1)
        if _TOKEN_EXPANSION.search(line) and line.strip() not in _ALLOWED_TOKEN_LINES
    ]


def _python_blocks(script: Path) -> list[str]:
    return _PY_BLOCK.findall(script.read_text(encoding="utf-8"))


def test_setup_sh_expands_the_database_url_only_in_its_export_line():
    assert _EXPORT_LINE in SETUP_SH.read_text(encoding="utf-8")
    assert _expansions(SETUP_SH) == []


def test_the_docker_entrypoint_expands_the_database_url_only_in_its_guard():
    assert _GUARD_LINE in ENTRYPOINT_SH.read_text(encoding="utf-8")
    assert _expansions(ENTRYPOINT_SH) == []


def test_the_docker_entrypoint_passes_the_oauth_token_to_no_process():
    assert _token_outside_builtins(ENTRYPOINT_SH) == []


def test_the_token_scan_refuses_an_argv_and_a_log(tmp_path: Path):
    script = tmp_path / "probe.sh"
    script.write_text(
        "\n".join(
            [
                *sorted(_ALLOWED_TOKEN_LINES),
                'if [[ -n "${CLAUDE_CODE_OAUTH_TOKEN:-}" ]]; then',
                '    echo "$CLAUDE_CODE_OAUTH_TOKEN" > creds.json',
                'python3 -c "import sys" "$CLAUDE_CODE_OAUTH_TOKEN"',
                'log "token: ${CLAUDE_CODE_OAUTH_TOKEN}"',
                'if echo "$CLAUDE_CODE_OAUTH_TOKEN" | python3 -c "import sys,json;'
                ' json.load(sys.stdin)" "$CLAUDE_CODE_OAUTH_TOKEN" 2>/dev/null; then',
                'echo x; curl -H "$CLAUDE_CODE_OAUTH_TOKEN" https://example.invalid',
            ]
        ),
        encoding="utf-8",
    )
    found = [entry.split(":")[1] for entry in _token_outside_builtins(script)]
    # The four allowed lines pass; every other expansion is flagged, a
    # builtin one included, so an edit to an allowed line cannot slip through.
    assert found == ["5", "6", "7", "8", "9", "10"]


def test_the_entrypoint_writes_the_token_it_reads_from_the_environment(
    tmp_path: Path,
):
    blocks = [b for b in _python_blocks(ENTRYPOINT_SH) if "claudeAiOauth" in b]
    assert len(blocks) == 1
    code = blocks[0].replace("$CLAUDE_HOME", str(tmp_path))
    env = dict(os.environ, CLAUDE_CODE_OAUTH_TOKEN=_SECRET)
    subprocess.run([sys.executable, "-c", code], env=env, timeout=60, check=True)
    creds = json.loads((tmp_path / ".credentials.json").read_text("utf-8"))
    assert creds["claudeAiOauth"]["accessToken"] == _SECRET


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
