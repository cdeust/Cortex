"""The telemetry log follows the same disposable root as every other store."""

from __future__ import annotations

import json
import os
import subprocess
import sys


def test_fresh_process_respects_configuration_root(tmp_path):
    isolated = tmp_path / "claude"
    script = (
        "from mcp_server.core import telemetry; "
        "telemetry.record('fixture', latency_ms=0); "
        "print(telemetry.summary()['log_path'])"
    )
    env = dict(os.environ, CORTEX_CLAUDE_DIR=str(isolated))
    env.pop("CORTEX_TELEMETRY_DISABLED", None)
    result = subprocess.run(
        [sys.executable, "-c", script],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    expected = isolated / "methodology" / "telemetry.jsonl"
    assert result.stdout.strip() == str(expected)
    assert json.loads(expected.read_text())["op"] == "fixture"
