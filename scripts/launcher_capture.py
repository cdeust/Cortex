"""Exclude disabled captures before backend resolution and dependency bootstrap.

source: ADR-0743"""

from __future__ import annotations

import io
import json
import os
import sys


def skip_capture() -> bool:
    """Run only for a non-full capture invocation after plugin path setup."""
    from mcp_server.hooks._headless_guard import exit_if_headless_authoring_child  # noqa: PLC0415 — plugin path is established by launcher.main before this entry

    exit_if_headless_authoring_child()
    if sys.stdin.isatty():
        return False
    try:
        raw = sys.stdin.read()
    except Exception as exc:  # noqa: BLE001 — same visible failure boundary as launcher.run_module
        print(
            "[cortex-launcher] Failed to run "
            f"mcp_server.hooks.post_tool_capture: {exc}",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc
    sys.stdin = io.StringIO(raw)
    try:
        event = json.loads(raw.strip())
    except json.JSONDecodeError:
        return False
    if not isinstance(event, dict) or not isinstance(event.get("tool_name", ""), str):
        return False
    return _exclude(event)


def _exclude(event: dict) -> bool:
    from mcp_server.hooks._capture_mode import HIGH_VALUE_TOOLS, capture_skip_reason  # noqa: PLC0415 — pure policy, resolvable only after plugin path setup

    reason = capture_skip_reason(
        os.environ.get("CORTEX_CAPTURE_MODE", "full"),
        event.get("tool_name", ""),
        HIGH_VALUE_TOOLS,
    )
    if reason is None:
        return False
    from mcp_server.hooks.post_tool_capture import _log  # noqa: PLC0415 — exact existing log at terminal exclusion only; admitted modules still run once

    _log(reason)
    return True
