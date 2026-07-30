"""Headless authoring worker — drains the curation-gap queue.

This is the actuator Meadows' leverage-point audit identified as
missing (2026-05-18). The gap detector knows what's missing; the
``curate_wiki`` tool builds prompts for the LLM; but until now the
loop terminated in a queue waiting for a human to open a Claude Code
session and consume the jobs interactively. The drain rate was zero
because the actuator was disconnected.

The worker connects sensor → actuator. It:

  1. Walks the wiki for pages with ``curation_gaps`` in frontmatter.
  2. For each page, picks the highest-leverage gap (the first one
     listed — see ``FILE_DOC_SECTIONS`` for ordering) plus enough
     source context that the LLM can answer it.
  3. Calls the user's Claude Code session via the ``claude -p`` CLI
     to author the missing section. No API key configuration needed
     — Claude Code's existing credentials carry through.
  4. Rewrites the page: the ``_(missing — needs: <description>)_``
     marker is replaced with the authored content; the
     ``curation_gaps`` frontmatter list shrinks; the ``lifecycle``
     promotes from ``needs-curation`` toward ``draft`` then
     ``accepted`` as more gaps fill.

The worker is per-cycle bounded — it drains at most ``MAX_DRAINS``
pages per invocation so a single cycle doesn't monopolise the
session. Subsequent ``consolidate_background`` runs drain the rest.

Failure handling: a failed LLM call leaves the page untouched. The
gap stays in the queue, the next cycle retries. The page is never
corrupted; the marker is only replaced after a successful LLM
response.

Module layout (split 2026-06-30 to satisfy the 500-line size limit
without changing behaviour — strategy B in the refactor brief): this
module remains the stable public import surface. It defines the
constants, the dataclass types, and ``_claude_invoke`` (whose security
controls are kept verbatim here), then re-exports the candidate
scanners, drain operations, and the concurrent cycle from sibling
modules:

  * ``authoring_prompts``    — prompt builders, parsers, gap markers.
  * ``page_io``              — frontmatter parse/rewrite, file reads,
                               anchor-page prompt + writer.
  * ``candidate_scan``       — ``_scan_pages_with_gaps`` /
                               ``_collect_anchor_candidates``.
  * ``drain_operations``     — ``drain_one`` / ``drain_all_gaps_on_page``
                               / ``drain_missing_anchors``.
  * ``cycle_orchestration``  — ``run_headless_authoring_cycle``.

The scanners and the cycle resolve the patchable names
(``CORTEX_HEADLESS_*``, ``_collect_anchor_candidates``,
``_scan_pages_with_gaps``) as attributes of THIS module at call time,
so ``monkeypatch.setattr(headless_authoring, ...)`` is observed.

Import direction (fixed 2026-07-30, issue #237): the four siblings above
used to import THIS module back at their own module top (``from . import
headless_authoring as _root``), which deadlocked any fresh interpreter
that imported one of them before this module finished initializing
(partial-module ``ImportError`` — reproducible with e.g. ``python -c
"import mcp_server.handlers.consolidation.candidate_scan"``). Each
sibling now resolves ``_root`` with a deferred, function-scoped import
instead (``# noqa: PLC0415 — import cycle``, per pyproject.toml's
named exemption for this family) — the load-time back-reference is
gone, so every sibling imports cleanly on its own, while the call-time
attribute lookup that makes ``monkeypatch.setattr(headless_authoring,
...)`` observable is unchanged.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
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


# ── Environment-configured knobs ────────────────────────────────────────
#
# Read at import time so values are stable for the process lifetime.
# All defaults are POLICY CAPS — operational safety rails bounding
# one cycle's resource consumption.  They are NOT scientifically
# measured constants: tuning them to match your hardware and cost
# tolerance via env vars is expected and encouraged.


def _env_int(name: str, default: int) -> int:
    """Return int from env var ``name``, or ``default`` when absent/invalid.

    Pre-condition:  ``default`` is a non-negative int.
    Post-condition: returns a valid int; never raises; logs on bad values.
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

    Pre-condition:  ``default`` is a non-negative float.
    Post-condition: returns a valid float; never raises; logs on bad values.
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
class CycleBudget:
    """Per-cycle wall-clock + USD budget tracker.

    Pre-condition:  ``deadline`` is a ``time.monotonic()`` value in the
                    future; ``usd_cap`` is a float (<=0 means unlimited).
    Invariant:      ``usd_spent`` is monotonically non-decreasing.

    Concurrency note: with CORTEX_HEADLESS_CONCURRENCY > 1, multiple
    coroutines can see ``exhausted() == False`` simultaneously before any
    of them has charged the budget.  The USD cap is therefore a SOFT
    ceiling with overshoot of at most ``concurrency - 1`` calls beyond
    the cap.  This is acceptable for an operational safety rail.
    """

    deadline: float  # time.monotonic() timestamp
    usd_cap: float  # <=0 means no USD cap
    usd_spent: float = field(default=0.0)

    def time_left(self) -> float:
        """Remaining seconds until deadline (negative when expired)."""
        return self.deadline - time.monotonic()

    def exhausted(self) -> bool:
        """True when wall-clock time is up OR the USD cap is reached."""
        if self.time_left() <= 0:
            return True
        return self.usd_cap > 0 and self.usd_spent >= self.usd_cap

    def charge(self, usd: float) -> None:
        """Add ``usd`` to the running spend.

        Pre-condition:  ``usd`` >= 0.
        Post-condition: ``self.usd_spent`` incremented by ``usd``.
        """
        self.usd_spent += usd


@dataclass
class DrainResult:
    """One drain attempt's outcome."""

    page_path: str
    gap: str
    status: str  # "filled" | "failed" | "skipped"
    duration_ms: int
    detail: str = ""


@dataclass
class CycleSummary:
    """Per-invocation roll-up with budget telemetry."""

    pages_scanned: int
    pages_with_gaps: int
    drains_attempted: int
    drains_filled: int
    drains_failed: int
    duration_ms: int
    results: list[DrainResult]
    # Budget telemetry fields (added in throttle refactor — callers that
    # access only the original fields are not affected).
    usd_spent: float = 0.0
    # wall_clock_ms is intentionally equal to duration_ms for the cycle: both
    # measure the cycle's wall-clock span. Kept as a distinct, explicitly-named
    # field because wiki_maintenance's telemetry dict emits both keys; the
    # original duration_ms is retained for pre-throttle callers.
    wall_clock_ms: int = 0
    skipped_budget: int = 0


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


async def _claude_invoke(
    prompt: str,
    *,
    cwd: str | None = None,
    source_root: str | None = None,
    timeout: float | None = None,
) -> InvokeResult:
    """Run ``claude -p`` asynchronously and return an InvokeResult.

    Uses ``asyncio.create_subprocess_exec`` + ``asyncio.wait_for`` so
    the call is non-blocking on the event loop.  On timeout the
    subprocess is killed and an empty InvokeResult is returned.

    The argv and child environment — including the full audit-B-1 security
    argument for both agents mode (the default, loading the user's zetetic
    roster under a hard write/exec ceiling) and solo ``--safe-mode`` mode —
    are built by ``claude_cli._build_argv`` / ``claude_cli._subprocess_env``.
    Auth is subscription-by-default, ``CORTEX_HEADLESS_AUTH=api`` opt-in.

    Response parsing relies on ``--output-format json``: ``result`` (assistant
    text) and ``total_cost_usd`` (client-side spend). ``usage`` / ``is_error``
    are NOT guaranteed in the CLI JSON — errors are detected via subprocess
    returncode only.

    The prompt is fed via STDIN, not as a positional argv element: the
    variadic ``--add-dir`` would otherwise swallow a trailing prompt and the
    CLI would error "Input must be provided". See ``claude_cli._build_argv``.
    """
    argv = _build_argv(source_root)

    call_timeout = timeout if timeout is not None else float(CLAUDE_CALL_TIMEOUT_SEC)

    # Subscription by default + hook-neutralising child flag; API key passes
    # through only on CORTEX_HEADLESS_AUTH=api opt-in. See claude_cli.
    child_env = _subprocess_env()

    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=child_env,
        )
    except FileNotFoundError:
        logger.warning("headless-authoring: claude binary not found on PATH")
        return InvokeResult(text=None, cost_usd=0.0)
    except Exception as exc:  # noqa: BLE001 — last-resort boundary — failure is logged; degraded mode continues
        logger.warning("headless-authoring: failed to start claude subprocess: %s", exc)
        return InvokeResult(text=None, cost_usd=0.0)

    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(input=prompt.encode("utf-8")), timeout=call_timeout
        )
    except asyncio.TimeoutError:
        logger.warning(
            "headless-authoring: claude -p timed out after %.0fs", call_timeout
        )
        return InvokeResult(text=None, cost_usd=0.0)
    except Exception as exc:  # noqa: BLE001 — last-resort boundary — failure is logged; degraded mode continues
        logger.warning("headless-authoring: claude -p communicate failed: %s", exc)
        return InvokeResult(text=None, cost_usd=0.0)
    finally:
        # CancelledError is a BaseException — it escapes the except clauses above.
        # Without this finally, a cancelled drain leaves a zombie subprocess.
        # Covers the timeout path too (returncode is None after wait_for cancels
        # communicate), so the kill lives in one place.
        if proc.returncode is None:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            await proc.wait()

    stdout = stdout_bytes.decode("utf-8", errors="replace") if stdout_bytes else ""
    stderr = stderr_bytes.decode("utf-8", errors="replace") if stderr_bytes else ""

    if proc.returncode != 0:
        logger.warning(
            "headless-authoring: claude -p exit %d stderr=%r",
            proc.returncode,
            stderr[:300],
        )
        return InvokeResult(text=None, cost_usd=0.0)

    stdout = stdout.strip()
    if not stdout:
        return InvokeResult(text=None, cost_usd=0.0)

    # Parse --output-format json response.
    # Documented fields (source: code.claude.com/docs/en/headless):
    #   result (str) — the assistant text
    #   total_cost_usd (float) — client-side cost estimate
    # ``usage`` and ``is_error`` are NOT guaranteed — use returncode only.
    try:
        data = json.loads(stdout)
        text: str | None = data.get("result") or None
        cost_usd = float(data.get("total_cost_usd") or 0.0)
    except (json.JSONDecodeError, ValueError):
        # Defensive: returncode==0 but JSON parse failed.  This can happen
        # if --output-format json isn't supported by an older claude CLI
        # build.  Treat raw stdout as the text so we degrade gracefully
        # rather than losing a successful response.
        logger.debug(
            "headless-authoring: JSON parse failed (returncode=0); "
            "treating raw stdout as text (cost unknown)"
        )
        text = stdout or None
        cost_usd = 0.0

    return InvokeResult(text=text, cost_usd=cost_usd)


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
# load-order-sensitive anymore. The imports stay after the constant/type/
# ``_claude_invoke`` definitions purely for readability (this module
# defines its own public surface before re-exporting the rest of it).

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
