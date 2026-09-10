"""Headless authoring worker — drains the curation-gap queue.

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

source: ADR-0361"""

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


# source: ADR-0361


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


# source: ADR-0361
CORTEX_HEADLESS_CONCURRENCY: int = _env_int("CORTEX_HEADLESS_CONCURRENCY", 4)

# Per-cycle wall-clock deadline (seconds).
# Policy cap — 300 s keeps each consolidate cycle latency bounded.
CORTEX_HEADLESS_BUDGET_SEC: float = _env_float("CORTEX_HEADLESS_BUDGET_SEC", 300.0)

# source: ADR-0361
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

# source: ADR-0361
CORTEX_HEADLESS_AGENTS: int = _env_int("CORTEX_HEADLESS_AGENTS", 1)


# ── Core data types ───────────────────────────────────────────────────────


@dataclass
class InvokeResult:
    """Outcome of one ``claude -p`` call.

    source: ADR-0361"""

    text: str | None  # None on failure
    cost_usd: float  # client-side spend estimate; 0.0 when unavailable


@dataclass
class _AnchorCandidate:
    """One missing groundable anchor to author.

    source: ADR-0361"""

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


# source: ADR-0361

from .cycle_types import (  # noqa: E402
    CycleBudget,
    CycleSummary,
    DrainResult,
    cycle_budget_charge,
    cycle_budget_exhausted,
    cycle_budget_time_left,
)
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
    "cycle_budget_time_left",
    "cycle_budget_exhausted",
    "cycle_budget_charge",
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
