"""Wedge-detection silence window for the MCP stdio client.

Applies ONLY to calls whose server config opted out of a wall-clock cap
(``callTimeoutMs: 0`` — the ingestion path: ap_bridge, pipeline_discovery).
For those calls there is deliberately NO ceiling on total call duration:
a fresh ``analyze_codebase`` of a large repository legitimately exceeds
any fixed bound, and killing a live ingestion mid-flight is worse than
waiting (owner requirement 2026-08-14; measured 2026-08-06: a wall-clock
cap killed an actively-progressing ingest walking a 1.1 GB tree).

What must still fail is a WEDGED child. The 2026-06-11 RCA case sat at
0% CPU with no output for 4.5+ hours (reader bound to a closed event
loop). Silence is what distinguishes wedged from slow: a live indexer
keeps emitting progress on stderr, a wedged child emits nothing. The
value below is therefore a bound on child SILENCE (no stdout or stderr
output), not on call duration.
"""

from __future__ import annotations

import os

# Default silence window (seconds) before a no-cap call is declared
# wedged. 600s = 10x the measured 32s success latency of an
# analyze/ingest run on the Cortex repo (live incident 2026-06-11:
# call 1 completed in 32s). As a bound on total *silence* it is strictly
# more conservative than the wall-clock ceiling it replaces: any child
# output resets the window. source: ingest stdio-deadlock RCA 2026-06-11.
_DEFAULT_CALL_TIMEOUT_S = 600.0
_ENV_VAR = "CORTEX_MCP_CALL_TIMEOUT_S"

# Wall-clock ceiling (seconds) for INTERACTIVE AP read-path calls
# (search_codebase, get_symbol, get_context, get_impact, get_processes,
# query_graph, health_check). Unlike indexing, a read/lookup is not
# legitimately long-running: an AP that connects but then wedges on such a
# call must degrade to graceful Cortex-only results, not stall the tool.
# The unbounded wedge window above (600s of SILENCE) is reserved for
# ingestion and is far too slow here — unified_search / get_causal_chain
# would hang for up to 10 minutes before falling back.
# source: interactive read-path ceiling. AP read tools are documented
# interactive (unified_search / get_causal_chain target <200ms,
# docs/mcp-tools.md); 30s is a wide margin over that interactive target yet
# 20x below the 600s indexing wedge window, so a wedged AP degrades in
# seconds instead of minutes.
_DEFAULT_INTERACTIVE_CALL_TIMEOUT_S = 30.0
_INTERACTIVE_ENV_VAR = "CORTEX_AP_INTERACTIVE_TIMEOUT_S"


def default_call_timeout_s() -> float:
    """Return the configured wedge silence window in seconds.

    Reads ``CORTEX_MCP_CALL_TIMEOUT_S`` (positive float) when set and valid;
    otherwise returns the documented default. A non-positive or malformed
    override falls back to the default rather than disabling the window —
    an unbounded wait on a silent child is the exact failure this guard
    exists to prevent.
    """
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

    Reads ``CORTEX_AP_INTERACTIVE_TIMEOUT_S`` (positive float) when set and
    valid; otherwise returns the documented default. A non-positive or
    malformed override falls back to the default — an unbounded interactive
    call is exactly the hang this ceiling exists to prevent.
    """
    raw = os.environ.get(_INTERACTIVE_ENV_VAR)
    if raw:
        try:
            val = float(raw)
            if val > 0:
                return val
        except (TypeError, ValueError):
            pass
    return _DEFAULT_INTERACTIVE_CALL_TIMEOUT_S
