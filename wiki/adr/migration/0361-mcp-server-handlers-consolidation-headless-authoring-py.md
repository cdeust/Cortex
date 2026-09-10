# ADR-0361: mcp_server/handlers/consolidation/headless_authoring.py implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `mcp_server/handlers/consolidation/headless_authoring.py`; original SHA-256 `ef01f1cfc4a61263b25b9a9c984e8bdc310a9cce118720537dd9ec03e8fa7917`.

## Original docstring, lines 1–49

````text
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
````

## Original comment, lines 77–79

````text
# ── Environment-configured knobs — read at import time so values stay
# stable for the process lifetime. All defaults are POLICY CAPS, not
# measured constants: tune via env vars to match your hardware/cost. ──
````

## Original comment, lines 120–122

````text
# Max concurrent ``claude -p`` subprocesses per cycle.
# Policy cap — not a measured constant.  Default 4 is conservative for
# a 4-core laptop; raise to 8–16 for a server host.
````

## Original comment, lines 129–133

````text
# Per-cycle USD ceiling.  <=0 means unlimited.
# POLICY CAP — operational safety rail bounding one cycle's API spend.
# NOT a measured scientific constant — tunable via env to match your
# cost tolerance.  Default 5.0 USD is conservative for testing; raise
# to 20–50 USD for production batch runs.
````

## Original comment, lines 147–158

````text
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
````

## Original docstring, lines 167–173

````text
"""Outcome of one ``claude -p`` call.

    ``text`` is None when the call failed (timeout, missing binary,
    non-zero exit, or empty response).  ``cost_usd`` is 0.0 when the
    CLI omits the field or JSON parse fails — we degrade gracefully and
    never crash on a missing cost signal.
    """
````

## Original docstring, lines 181–181

````text
"""One missing groundable anchor to author (pre-screened, no I/O)."""
````

## Original comment, lines 207–214

````text
# ── Re-exports — the public import surface (see module docstring) ─────────
#
# These siblings resolve THIS module as ``_root`` via a deferred,
# function-scoped import (issue #237) and read the patchable names off it
# at call time — no back-reference at module scope, so nothing below is
# load-order-sensitive anymore. The imports stay after the constant/type
# definitions purely for readability (this module defines its own public
# surface before re-exporting the rest of it).
````

