"""Headless authoring worker — drains the curation-gap queue.

This is the actuator Meadows' leverage-point audit identified as
missing (2026-05-18): the gap detector knows what's missing and
``curate_wiki`` builds prompts, but the loop terminated in a queue
waiting for a human to consume the jobs interactively. The drain rate
was zero because the actuator was disconnected.

The worker connects sensor -> actuator: walks the wiki for pages with
``curation_gaps``, calls the user's Claude Code session via ``claude
-p`` to author the missing section (no API key needed — existing
credentials carry through), and rewrites the page (marker replaced,
``curation_gaps`` shrinks, ``lifecycle`` promotes toward ``accepted``).
Per-cycle bounded (``MAX_DRAINS_PER_CYCLE``); subsequent
``consolidate_background`` runs drain the rest. A failed LLM call
leaves the page untouched — never corrupted, only replaced on success.

Module layout (split 2026-06-30, then again 2026-07-30 for #276, to
satisfy the size limit without changing behaviour): this module
remains the stable public import surface, defining the constants and
dataclass types, then re-exporting everything else:

  * ``authoring_prompts``   — prompt builders, parsers, gap markers.
  * ``page_io``             — frontmatter parse/rewrite, file reads,
                              anchor-page prompt + writer.
  * ``candidate_scan``      — ``_scan_pages_with_gaps`` /
                              ``_collect_anchor_candidates``.
  * ``drain_operations``    — ``drain_one`` / ``drain_all_gaps_on_page``.
  * ``anchor_authoring``    — ``drain_missing_anchors``.
  * ``cycle_orchestration`` — ``run_headless_authoring_cycle``.
  * ``claude_invoke``       — ``_claude_invoke`` (the ``claude -p``
                              subprocess call; security controls live
                              in the argv/env builders in ``claude_cli``).

The scanners and the cycle resolve the patchable names
(``CORTEX_HEADLESS_*``, ``_collect_anchor_candidates``,
``_scan_pages_with_gaps``) as attributes of THIS module at call time,
so ``monkeypatch.setattr(headless_authoring, ...)`` is observed.

Import direction (fixed 2026-07-30, issue #237): the siblings above
used to import THIS module back at their own module top, deadlocking
any fresh interpreter that imported one of them first (partial-module
``ImportError`` — reproducible with e.g. ``python -c "import
mcp_server.handlers.consolidation.candidate_scan"``). Each sibling now
resolves ``_root`` with a deferred, function-scoped import instead
(``# noqa: PLC0415 — import cycle``, per pyproject.toml's named
exemption for this family) — the load-time back-reference is gone, the
call-time patchability above is unchanged.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from .authoring_prompts import _delegation_hint

logger = logging.getLogger(__name__)


# Per-cycle drain budget. Tuned so the worker finishes within a
# reasonable wall-clock window even when ``claude -p`` takes 15-30s
# per call.
MAX_DRAINS_PER_CYCLE: int = 8

# Wall-clock cap per LLM call. File-doc gap fills typically complete
# in 10-20 seconds. Anchor pages (architecture, services, …) carry
# more context and need 60-120s. 180s is the bound past which we
# abort the subprocess and move on.
CLAUDE_CALL_TIMEOUT_SEC: int = 180

# Claude CLI binary. Resolved via PATH; the SessionStart hook already
# requires `claude` to be installed.
_CLAUDE_BIN = "claude"


# ── Environment-configured knobs — read at import time so values stay
# stable for the process lifetime. All defaults are POLICY CAPS, not
# measured constants: tune via env vars to match your hardware/cost. ──


def _env_int(name: str, default: int) -> int:
    """Return int from env var ``name``, or ``default`` when absent/invalid.
    Never raises; logs on a bad value.
    """
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning(
            "headless-authoring: %s=%r is not an int; using default %d",
            name,
            raw,
            default,
        )
        return default


def _env_float(name: str, default: float) -> float:
    """Return float from env var ``name``, or ``default`` when absent/invalid.
    Never raises; logs on a bad value.
    """
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning(
            "headless-authoring: %s=%r is not a float; using default %g",
            name,
            raw,
            default,
        )
        return default


# Max concurrent ``claude -p`` subprocesses per cycle.
# Policy cap — not a measured constant.  Default 4 is conservative for
# a 4-core laptop; raise to 8–16 for a server host.
CORTEX_HEADLESS_CONCURRENCY: int = _env_int("CORTEX_HEADLESS_CONCURRENCY", 4)

# Per-cycle wall-clock deadline (seconds).
# Policy cap — 300 s keeps each consolidate cycle latency bounded.
CORTEX_HEADLESS_BUDGET_SEC: float = _env_float("CORTEX_HEADLESS_BUDGET_SEC", 300.0)

# Per-cycle USD ceiling.  <=0 means unlimited.
# POLICY CAP — operational safety rail bounding one cycle's API spend.
# NOT a measured scientific constant — tunable via env to match your
# cost tolerance.  Default 5.0 USD is conservative for testing; raise
# to 20–50 USD for production batch runs.
CORTEX_HEADLESS_USD_BUDGET: float = _env_float("CORTEX_HEADLESS_USD_BUDGET", 5.0)

# Per-cycle anchor drain cap (was hard-coded 30; env-tunable, default 8
# = MAX_DRAINS_PER_CYCLE, to keep cycles within the wall-clock budget).
CORTEX_HEADLESS_MAX_ANCHOR_DRAINS: int = _env_int(
    "CORTEX_HEADLESS_MAX_ANCHOR_DRAINS", MAX_DRAINS_PER_CYCLE
)

# Per-cycle file-doc drain cap.
CORTEX_HEADLESS_MAX_FILE_DRAINS: int = _env_int(
    "CORTEX_HEADLESS_MAX_FILE_DRAINS", MAX_DRAINS_PER_CYCLE
)

# Agents mode — selects the ``claude -p`` invocation strategy.
#   1 (default): load the user's zetetic agent ROSTER (--setting-sources user)
#       and give the top-level authoring agent the ``Task`` tool so it can
#       delegate read-only codebase analysis to specialists (architect,
#       engineer, …). A hard ``--disallowedTools`` ceiling (Write/Edit/Bash/
#       NotebookEdit) propagates to every spawned subagent, so the roster can
#       analyse but never write or execute. User hooks load too — they are
#       neutralised by CORTEX_HEADLESS_AUTHORING_CHILD (see _subprocess_env).
#   0: hardened solo path — ``--safe-mode`` config isolation, no roster, no
#       Task tool. Use when you want zero user-config surface in the child.
# Policy knob, not a measured constant. Default 1 reflects the design intent:
# diverse specialist grounding beats a single generalist pass.
CORTEX_HEADLESS_AGENTS: int = _env_int("CORTEX_HEADLESS_AGENTS", 1)


# ── Core data types ───────────────────────────────────────────────────────


@dataclass
class InvokeResult:
    """Outcome of one ``claude -p`` call.

    ``text`` is None when the call failed (timeout, missing binary,
    non-zero exit, or empty response).  ``cost_usd`` is 0.0 when the
    CLI omits the field or JSON parse fails — we degrade gracefully and
    never crash on a missing cost signal.
    """

    text: str | None  # None on failure
    cost_usd: float  # client-side spend estimate; 0.0 when unavailable


@dataclass
class _AnchorCandidate:
    """One missing groundable anchor to author (pre-screened, no I/O)."""

    domain: str
    scope_name: str
    scope_title: str
    scope_description: str
    source_root: str
    suggested_path: str
    suggested_kind: str


def _delegation_hint_for(kind: str) -> str | None:
    """Return the Task-delegation prompt paragraph for ``kind``, or None.

    Gated on ``CORTEX_HEADLESS_AGENTS`` (module global — patchable in tests).
    In solo mode the ``claude -p`` call has no ``Task`` tool and no agent
    roster, so a delegation hint would point the model at an unavailable
    tool; return None to omit it. In agents mode, delegate to
    ``authoring_prompts._delegation_hint`` (the pure string builder).
    """
    if not CORTEX_HEADLESS_AGENTS:
        return None

    return _delegation_hint(kind)


# ── Re-exports — the public import surface (see module docstring) ─────────
#
# These siblings resolve THIS module as ``_root`` via a deferred,
# function-scoped import (issue #237) and read the patchable names off it
# at call time — no back-reference at module scope, so nothing below is
# load-order-sensitive anymore. The imports stay after the constant/type
# definitions purely for readability (this module defines its own public
# surface before re-exporting the rest of it).

from .cycle_types import CycleBudget, CycleSummary, DrainResult  # noqa: E402
from .claude_cli import _build_argv, _subprocess_env  # noqa: E402
from .candidate_scan import (  # noqa: E402
    _collect_anchor_candidates,
    _scan_pages_with_gaps,
)
from .drain_operations import (  # noqa: E402
    drain_all_gaps_on_page,
    drain_one,
)
from .anchor_authoring import drain_missing_anchors  # noqa: E402
from .cycle_orchestration import run_headless_authoring_cycle  # noqa: E402
from .claude_invoke import _claude_invoke  # noqa: E402

__all__ = [
    "InvokeResult",
    "CycleBudget",
    "DrainResult",
    "CycleSummary",
    "_AnchorCandidate",
    "_claude_invoke",
    "_collect_anchor_candidates",
    "_scan_pages_with_gaps",
    "drain_one",
    "drain_all_gaps_on_page",
    "drain_missing_anchors",
    "run_headless_authoring_cycle",
    "CORTEX_HEADLESS_CONCURRENCY",
    "CORTEX_HEADLESS_BUDGET_SEC",
    "CORTEX_HEADLESS_USD_BUDGET",
    "CORTEX_HEADLESS_MAX_FILE_DRAINS",
    "CORTEX_HEADLESS_MAX_ANCHOR_DRAINS",
    "CORTEX_HEADLESS_AGENTS",
    "CLAUDE_CALL_TIMEOUT_SEC",
    "_CLAUDE_BIN",
    "_build_argv",
    "_subprocess_env",
    "_delegation_hint_for",
    "MAX_DRAINS_PER_CYCLE",
]
