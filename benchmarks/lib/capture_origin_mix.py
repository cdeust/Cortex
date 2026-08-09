"""Realistic capture_origin mixture for benchmark corpora (issue #368 fix).

Why this exists: the trust-factor gated arm
(docs/provenance/trust-factor-calibration.md) reported LME identical to four
decimals across W in {1.0, 0.7, 0.6, 0.5} because LME/LoCoMo/BEAM never set
capture_origin on the memories they insert -- every row fell through to the
column default 'unknown' (pg_schema.py, pg_store.py:567), which
mcp_server.core.capture_origin.trust_factor demotes uniformly. A uniform
multiplier cannot change WRRF order, so the gated arm was structurally
incapable of measuring W's effect on ranking; it could only prove the
non-regression of everything else in the pipeline.

This module assigns each benchmark memory a capture_origin drawn from the
distribution that ACTUALLY occurs in production Cortex usage, so the gated
arm mixes trusted and untrusted content the way a live store does and can
therefore discriminate W.
"""

from __future__ import annotations

import numpy as np

# source: measured 2026-08-10 on this machine's own Claude Code history --
#   886 session transcripts under ~/.claude/projects/**/*.jsonl (the only
#   representative "existing store" of real Cortex-adjacent usage available
#   in this environment; the local memory.db predates the capture_origin
#   migration and carries no such column to sample). Two greps:
#
#   1) tool_use frequency for every tool name that
#      mcp_server.core.capture_origin.classify_capture_origin maps to a
#      non-UNKNOWN origin (issue #365 _LOCAL_ACTION_TOOLS / _NETWORK_TOOLS),
#      restricted to the tools hooks/post_tool_capture.py actually
#      auto-captures (_HIGH_VALUE_TOOLS + _LIGHT_VALUE_TOOLS +
#      _CONDITIONAL_TOOLS):
#
#        grep -rhoE '"name": ?"(Edit|Write|MultiEdit|NotebookEdit|
#          NotebookRead|Bash|Read|Glob|Grep|WebFetch|WebSearch)"'
#          ~/.claude/projects/ | sort | uniq -c
#
#      -> Bash 29088, Read 5656, Edit 3992, Write 1162, WebFetch 583,
#         WebSearch 466, Glob 5, MultiEdit/NotebookEdit/NotebookRead/Grep 0.
#      local_action (Bash+Read+Edit+Write+Glob) = 39903
#      network (WebFetch+WebSearch)             = 1049
#
#   2) explicit `remember` MCP tool_use calls (ORIGIN_DELIBERATE -- a direct
#      remember with no origin_tool resolves DELIBERATE per
#      handlers/remember.py) across the same transcripts:
#
#        grep -rhoE '"name": ?"[a-zA-Z0-9_.-]*remember[a-zA-Z0-9_.-]*"'
#          ~/.claude/projects/ | sort | uniq -c
#
#      -> mcp__plugin_cortex_cortex__remember 278,
#         mcp__plugin_hypermnesia-mcp_cortex__remember 83 => deliberate = 361
#
#   Pool = 39903 + 1049 + 361 = 41313.
#     local_action = 39903 / 41313 = 0.9659
#     network      =  1049 / 41313 = 0.0254
#     deliberate   =   361 / 41313 = 0.0087
#   Rounded to 3dp so the three sum to 1.000 exactly.
#
#   Limitation, stated rather than smoothed over: this is one user's
#   tool-call frequency, not a filtered count of rows that actually pass
#   _should_capture's length/content gates, and not a multi-user production
#   sample. It is nonetheless a measurement of real usage, not an invented
#   split, and it is the only "existing store" available to measure from in
#   this environment. unknown/legacy are omitted at 0.0: every current
#   writer (remember handler, post_tool_capture hook) resolves one of the
#   three origins below; legacy is written only once, by the migration,
#   never by a live write path, and no live writer produces unknown for a
#   tool name it recognises -- the measured 0.0 IS the production rate for a
#   fully-migrated store, not a gap in the count.
CAPTURE_ORIGIN_MIX: tuple[tuple[str, float], ...] = (
    ("local_action", 0.966),
    ("network", 0.025),
    ("deliberate", 0.009),
)

_ORIGINS = tuple(o for o, _ in CAPTURE_ORIGIN_MIX)
_WEIGHTS = tuple(w for _, w in CAPTURE_ORIGIN_MIX)

_SUM_TOLERANCE = 1e-9
assert abs(sum(_WEIGHTS) - 1.0) < _SUM_TOLERANCE, "CAPTURE_ORIGIN_MIX must sum to 1.0"

# Deterministic across runs (benchmarks/reproduce.sh's whole premise is "hit
# play, get the same numbers" -- see its module docstring). Not a calibrated
# quantity, just a fixed draw seed; any constant works, this one is arbitrary.
DEFAULT_SEED = 368


def assign_capture_origins(n: int, seed: int = DEFAULT_SEED) -> list[str]:
    """Return `n` capture_origin values drawn i.i.d. from CAPTURE_ORIGIN_MIX.

    Pre: n >= 0.
    Post: len(result) == n; each element is one of _ORIGINS; deterministic
    for a given (n, seed): same call, same output, every process.
    """
    rng = np.random.default_rng(seed)
    if n == 0:
        return []
    idx = rng.choice(len(_ORIGINS), size=n, p=_WEIGHTS)
    return [_ORIGINS[i] for i in idx]
