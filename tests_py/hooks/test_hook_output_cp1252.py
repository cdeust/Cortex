"""Real hook processes write UTF-8 to a pipe whose encoding is cp1252 (#688).

``PYTHONIOENCODING=cp1252`` gives a child the stdout a Windows pipe has, so the
failure reproduces on any platform: before the fix the hook died with
``UnicodeEncodeError`` on the ``U+27E6`` that opens every injection receipt.
The memory also carries accented, symbol and CJK characters, which cp1252
cannot all encode. This proves the output on a real OS pipe; it does not prove
anything about a Windows console or the Windows hook runner.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from mcp_server.handlers.remember import handler
from tests_py._hermetic_hook_env import hermetic_hook_env

MARKER = "ORCHID_CP1252_MARKER"
NON_ASCII = "décision ✓ 日本語"
RECEIPT_OPEN = "⟦"
PROJECT = "/tmp/project-cp1252"


def _store_decision() -> None:
    result = asyncio.run(
        handler(
            {
                "content": f"Decision: retain the ledger dossier layout {MARKER} "
                f"{NON_ASCII}",
                "force": True,
                "agent_topic": "engineer",
                "directory": PROJECT,
            }
        )
    )
    assert result["stored"], result


def _event(name: str) -> dict[str, str]:
    return {
        "hook_event_name": name,
        "cwd": PROJECT,
        "prompt": "ledger dossier layout decision",
        "source": "startup",
    }


def _run(argv: list[str], event: dict[str, str], tmp_path: Path):
    base = {
        k: v
        for k, v in os.environ.items()
        if k not in {"CLAUDE_PROJECT_ROOT", "PYTHONUTF8"}
    }
    env, project = hermetic_hook_env(base, tmp_path)
    env["PYTHONIOENCODING"] = "cp1252"
    return subprocess.run(
        [sys.executable, *argv],
        input=json.dumps(event).encode("utf-8"),
        capture_output=True,
        env=env,
        cwd=project,
    )


def _assert_utf8_injection(done: subprocess.CompletedProcess[bytes]) -> None:
    assert done.returncode == 0, done.stderr.decode("utf-8", "backslashreplace")
    assert b"UnicodeEncodeError" not in done.stderr
    text = done.stdout.decode("utf-8")
    assert RECEIPT_OPEN in text
    assert MARKER in text
    assert NON_ASCII in text


@pytest.mark.parametrize(
    ("module", "event_name"),
    [("auto_recall", "UserPromptSubmit"), ("session_start", "SessionStart")],
)
def test_hook_run_as_a_module_writes_utf8_to_a_cp1252_pipe(
    module: str, event_name: str, tmp_path: Path
) -> None:
    _store_decision()
    done = _run(["-m", f"mcp_server.hooks.{module}"], _event(event_name), tmp_path)
    _assert_utf8_injection(done)


def test_codex_console_entry_writes_utf8_to_a_cp1252_pipe(tmp_path: Path) -> None:
    _store_decision()
    done = _run(
        ["-m", "mcp_server.hooks.entry", "auto_recall"],
        _event("UserPromptSubmit"),
        tmp_path,
    )
    _assert_utf8_injection(done)
