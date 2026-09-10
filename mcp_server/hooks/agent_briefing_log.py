"""Stderr-only logging helper shared across the agent_briefing hook split.

source: ADR-0483"""

from __future__ import annotations

import sys

_LOG_PREFIX = "[cortex-agent-briefing]"


def _log(msg: str) -> None:
    print(f"{_LOG_PREFIX} {msg}", file=sys.stderr)
