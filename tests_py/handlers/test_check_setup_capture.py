"""``check_setup`` answers not-ready while every auto-capture is skipped (issue #660).

Runs the real handler in a clean process whose Cortex root holds the reporter's
evidence (skips, no processed capture). On main it answers ``ready: true``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _write_log(root: Path, rows: list[tuple[float, str]]) -> None:
    directory = root / "methodology"
    directory.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps({"ts": ts, "op": op, "ok": False}) for ts, op in rows]
    (directory / "telemetry.jsonl").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def test_check_setup_is_not_ready_while_every_capture_is_skipped(tmp_path) -> None:
    now = time.time()
    _write_log(tmp_path, [(now - 100 + i, "capture_skipped") for i in range(40)])
    script = (
        "import asyncio, json; from mcp_server.handlers.check_setup import handler;"
        "print(json.dumps(asyncio.run(handler())))"
    )
    env = dict(
        os.environ,
        CORTEX_CLAUDE_DIR=str(tmp_path),
        HOME=str(tmp_path),
        USERPROFILE=str(tmp_path),
        CORTEX_BACKEND="sqlite",
    )
    env.pop("DATABASE_URL", None)
    env.pop("CORTEX_TELEMETRY_DISABLED", None)
    run = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        cwd=REPO,
        env=env,
    )
    assert run.returncode == 0, run.stderr
    result = json.loads(run.stdout.splitlines()[-1])
    assert result["ready"] is False, result
    capture = [c for c in result["checks"] if c["name"] == "auto-capture"]
    assert len(capture) == 1 and capture[0]["ok"] is False
    assert "40 captures skipped and none ever processed" in capture[0]["detail"]
    assert result["fixes_needed"] >= 1
