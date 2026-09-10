"""MCP tool profiles — which of Cortex's ~51 tools a session registers.

source: ADR-0693"""

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

# source: ADR-0693

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
        raise ValueError(
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
                raise ValueError(f"{PROFILE_FLAG} requires a value: 'full' or 'lean'")
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


# source: ADR-0693


FULL_INSTRUCTIONS = (
    "Cortex cognitive profiling and persistent-memory MCP server "
    "('full' profile — every tool; the default). "
    "Use remember/recall explicitly on hosts without lifecycle hooks. The "
    "Claude Code plugin can additionally auto-capture and inject context; "
    "those hooks are not required by this server. Call query_methodology when "
    "a Claude Code session-history profile is available. "
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
    "Cortex persistent-memory MCP server ('lean' profile — the "
    "recall/onboarding surface). Use remember/recall explicitly on hosts "
    "without lifecycle hooks. Call query_methodology when a Claude Code "
    "session-history profile is available, then use unified_search and "
    "recall_hierarchical "
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
