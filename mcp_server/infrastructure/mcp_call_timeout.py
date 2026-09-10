"""Wedge-detection silence window for the MCP stdio client.

What must still fail is a WEDGED child. The 2026-06-11 RCA case sat at
0% CPU with no output for 4.5+ hours (reader bound to a closed event
loop). Silence is what distinguishes wedged from slow: a live indexer
keeps emitting progress on stderr, a wedged child emits nothing. The
value below is therefore a bound on child SILENCE (no stdout or stderr
output), not on call duration.

source: ADR-0531"""

from __future__ import annotations

import os

# source: ADR-0531
_DEFAULT_CALL_TIMEOUT_S = 600.0
_ENV_VAR = "CORTEX_MCP_CALL_TIMEOUT_S"

# source: ADR-0531
_DEFAULT_INTERACTIVE_CALL_TIMEOUT_S = 30.0
_INTERACTIVE_ENV_VAR = "CORTEX_AP_INTERACTIVE_TIMEOUT_S"


def default_call_timeout_s() -> float:
    """Return the configured wedge silence window in seconds.

    source: ADR-0531"""
    raw = os.environ.get(_ENV_VAR)
    if raw:
        try:
            val = float(raw)
            if val > 0:
                return val
        except (TypeError, ValueError):
            pass
    return _DEFAULT_CALL_TIMEOUT_S


def interactive_call_timeout_s() -> float:
    """Return the wall-clock ceiling for interactive AP read-path calls.

    source: ADR-0531"""
    raw = os.environ.get(_INTERACTIVE_ENV_VAR)
    if raw:
        try:
            val = float(raw)
            if val > 0:
                return val
        except (TypeError, ValueError):
            pass
    return _DEFAULT_INTERACTIVE_CALL_TIMEOUT_S
