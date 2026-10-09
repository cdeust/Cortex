"""Real pipes: a child Python reads UTF-8 bytes through the stdin reader.

The child runs with the locale forced to ASCII and UTF-8 mode off, so its
text-mode ``sys.stdin`` would mangle the bytes. This proves the reader on a
real OS pipe; it does not prove anything about Windows.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEXT = '{"tool_name": "Bash", "note": "supprimé — élève → 😍"}'
READ = (
    "import sys\n"
    "from mcp_server.hooks.stdin_event import read_event_text\n"
    "sys.stdout.buffer.write(read_event_text().encode('utf-8'))\n"
)


def _env(tmp_path: Path) -> dict[str, str]:
    env = dict(os.environ)
    for key in ("PYTHONIOENCODING", "PYTHONUTF8"):
        env.pop(key, None)
    env.update(
        LC_ALL="C",
        PYTHONUTF8="0",
        PYTHONCOERCECLOCALE="0",
        HOME=str(tmp_path),
        CORTEX_CLAUDE_DIR=str(tmp_path),
        CORTEX_MEMORY_STORE_BACKEND="sqlite",
    )
    return env


def _run(args: list[str], data: bytes, tmp_path: Path):
    return subprocess.run(
        [sys.executable, *args],
        input=data,
        capture_output=True,
        env=_env(tmp_path),
        cwd=ROOT,
        timeout=None,
    )


def test_reader_returns_the_utf8_bytes_intact_over_a_real_pipe(
    tmp_path: Path,
) -> None:
    done = _run(["-c", READ], TEXT.encode("utf-8"), tmp_path)
    assert done.returncode == 0, done.stderr
    assert done.stdout == TEXT.encode("utf-8")


def test_reader_fails_loudly_on_invalid_bytes_over_a_real_pipe(
    tmp_path: Path,
) -> None:
    done = _run(["-c", READ], b'{"note": "\xff\xfe"}', tmp_path)
    assert done.returncode != 0
    assert b"HookStdinDecodeError" in done.stderr


def test_real_hook_process_allows_a_utf8_event(tmp_path: Path) -> None:
    done = _run(
        ["-m", "mcp_server.hooks.decision_gate"], TEXT.encode("utf-8"), tmp_path
    )
    assert done.returncode == 0, done.stderr


def test_real_gate_process_fails_closed_on_invalid_bytes(tmp_path: Path) -> None:
    done = _run(["-m", "mcp_server.hooks.decision_gate"], b"\xff\xfe", tmp_path)
    assert done.returncode == 2
    assert b"fail closed" in done.stderr
