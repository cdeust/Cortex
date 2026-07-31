"""MCP tool profiles — which of Cortex's ~51 tools a session registers.

Cortex registers its whole tool surface to every client on every session
(issue #177): the largest fixed token cost in the ecosystem, paid before the
user types anything. A profile narrows that surface for sessions that only
need the common recall/onboarding loop, without removing any tool from the
`full` surface.

Two profiles:

- ``full`` — every registered tool. **The default.** Shrinking the default
  surface is a breaking change (a client that called a now-hidden tool would
  break), so — mirroring ``automatised-pipeline``'s ``ToolProfile`` reasoning
  and this wave's explicit decision — ``full`` stays the default. This
  diverges from #177 criterion 2's "default to the common-session profile";
  the divergence and its rationale are recorded in the CHANGELOG and PR.
- ``lean`` — the recall/onboarding surface an outside agent needs.

Selection precedence: ``--profile`` CLI flag > ``CORTEX_MCP_PROFILE`` env var
> ``full`` (matches the ``CORTEX_*`` runtime-toggle convention, e.g.
``CORTEX_RUNTIME``).

LEAN membership derivation (issue #177 criterion 1)
---------------------------------------------------
The set is derived from the documented tool tiers (``docs/mcp-tools.md``) and
the common-session workflow the issue itself characterises: a session doing
recall/onboarding "never calls ``wiki_migrate``, ``wiki_purge``,
``rebuild_profiles``, ``import_sessions``, ``backfill_memories`` or
``forget``". The runtime instrument that refines this per-deployment is
``get_telemetry`` (per-tool call counts in ``~/.claude/methodology/
telemetry.jsonl``); no committed telemetry corpus ships in-repo, so member-
ship is taxonomy-derived here and is intended to be tightened against a
deployment's own ``get_telemetry`` output rather than guessed wider.

The lean set is exactly the tools the recall/onboarding loop touches:
  - onboarding entry: ``query_methodology`` (CLAUDE.md: "Call
    query_methodology at the beginning of every session");
  - store / retrieve: ``remember``, ``recall``, ``unified_search``,
    ``recall_hierarchical``;
  - maintenance the loop runs itself: ``consolidate``;
  - health / diagnostics: ``memory_stats``, ``check_setup``;
  - wiki read side ("wiki basics"): ``wiki_read``, ``wiki_list``.
Every lean tool is read-only or idempotent-write; no destructive tool
(``forget``, ``wiki_purge``, ``wiki_migrate``, delete-class) is a member, so
the destructive surface is excluded — and, per criterion 5, gated on call.
"""

from __future__ import annotations

import os
import sys
from enum import Enum


class ToolProfile(str, Enum):
    """Which tool surface the server exposes for a session."""

    FULL = "full"
    LEAN = "lean"


# CLI flag / env var selecting the profile.
PROFILE_FLAG = "--profile"
PROFILE_ENV_VAR = "CORTEX_MCP_PROFILE"

# The recall/onboarding surface. See module docstring for the derivation.
# source: docs/mcp-tools.md tiers + issue #177 common-session characterisation.
LEAN_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "query_methodology",
        "remember",
        "recall",
        "unified_search",
        "recall_hierarchical",
        "consolidate",
        "memory_stats",
        "check_setup",
        "wiki_read",
        "wiki_list",
    }
)


def parse(value: str) -> ToolProfile:
    """Parse a profile name. Accepts exactly ``full`` and ``lean``.

    Precondition: ``value`` is any string.
    Postcondition: returns the matching ``ToolProfile`` or raises
    ``ValueError`` naming the accepted values.
    """
    try:
        return ToolProfile(value)
    except ValueError:
        raise ValueError(  # noqa: TRY003 — one-off message, not reused (§3.3)
            f"invalid profile {value!r}: expected 'full' or 'lean'"
        ) from None


def resolve(
    argv: list[str] | None = None, env: dict[str, str] | None = None
) -> ToolProfile:
    """Resolve the active profile from CLI args and the environment.

    Precondition: ``argv`` is the process args (program name already stripped
    is fine; the flag is searched positionally); ``env`` is a mapping.
    Postcondition: returns the flag's profile if ``--profile`` is present,
    else the env var's profile if set, else ``ToolProfile.FULL``. Raises
    ``ValueError`` for an unknown name in either source.
    """
    argv = list(argv if argv is not None else sys.argv[1:])
    env = env if env is not None else dict(os.environ)

    flag_value = _flag_value(argv)
    if flag_value is not None:
        return parse(flag_value)

    env_value = env.get(PROFILE_ENV_VAR)
    if env_value:
        return parse(env_value)

    return ToolProfile.FULL


def _flag_value(argv: list[str]) -> str | None:
    """Value of ``--profile`` / ``--profile=<v>`` in ``argv``; last wins.

    A trailing ``--profile`` with no value raises ``ValueError``.
    """
    found: str | None = None
    it = iter(range(len(argv)))
    for i in it:
        arg = argv[i]
        if arg == PROFILE_FLAG:
            if i + 1 >= len(argv):
                raise ValueError(f"{PROFILE_FLAG} requires a value: 'full' or 'lean'")  # noqa: TRY003 — one-off message, not reused (§3.3)
            found = argv[i + 1]
            next(it, None)  # consume the value
        elif arg.startswith(PROFILE_FLAG + "="):
            found = arg[len(PROFILE_FLAG) + 1 :]
    return found


def allows(profile: ToolProfile, tool_name: str) -> bool:
    """Whether ``tool_name`` is registered under ``profile``.

    ``full`` allows everything; ``lean`` allows exactly ``LEAN_TOOL_NAMES``.
    """
    if profile is ToolProfile.FULL:
        return True
    return tool_name in LEAN_TOOL_NAMES


# ── Per-profile initialize instructions (issue #177 criterion 3) ────────────
#
# The server describes itself in the shape it was started in. The FULL text
# preserves the historical onboarding line ("Call query_methodology…") so
# existing clients and the `test_mcp_server_has_instructions` contract are
# unchanged.

FULL_INSTRUCTIONS = (
    "Cortex cognitive profiling and persistent-memory system for Claude Code "
    "('full' profile — every tool; the default). "
    "Extracts reasoning signatures from session history and pre-loads them at "
    "session start. Call query_methodology at the beginning of every session. "
    "Use remember/recall for persistent thermodynamic memory across sessions; "
    "unified_search for retrieval across memories, wiki, and code; consolidate "
    "for maintenance (decay, compression, episodic→semantic CLS); the wiki_* "
    "tools for first-class pages; and the navigation tools "
    "(recall_hierarchical/drill_down/get_causal_chain) to traverse memory. "
    "Guided multi-tool workflows are published via prompts/list. Restart with "
    "--profile lean (or CORTEX_MCP_PROFILE=lean) for the recall/onboarding "
    "subset only."
)

LEAN_INSTRUCTIONS = (
    "Cortex persistent-memory system for Claude Code ('lean' profile — the "
    "recall/onboarding surface). Call query_methodology at the beginning of "
    "every session to load the cognitive profile, then remember/recall and "
    "unified_search for persistent memory across sessions, recall_hierarchical "
    "for fractal recall, consolidate for maintenance, memory_stats/check_setup "
    "for health, and wiki_read/wiki_list to read the wiki. The full "
    "profiling, curation, ingestion, and destructive-maintenance surface "
    "(including forget and the wiki_purge/wiki_migrate class) is hidden AND "
    "rejected on call in this profile; restart with --profile full to expose "
    "every tool. The session_recall prompt (prompts/list) guides the loop."
)


def instructions(profile: ToolProfile) -> str:
    """The ``initialize.instructions`` string for ``profile``."""
    return LEAN_INSTRUCTIONS if profile is ToolProfile.LEAN else FULL_INSTRUCTIONS
