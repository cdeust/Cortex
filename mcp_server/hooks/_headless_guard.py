"""Suppress Cortex hooks inside the headless wiki-authoring subprocess.

The headless authoring worker (``handlers.consolidation.headless_authoring``)
can spawn ``claude -p --setting-sources user`` so the user's full zetetic
agent roster authors wiki pages. ``--setting-sources user`` loads the user's
*agents* — but it also loads the user's *hooks*. Letting those hooks run
inside the authoring child is wrong on two counts:

* **Recursion.** The ``SessionEnd`` hook (:mod:`session_lifecycle`) runs the
  consolidation "dream" cycle, which re-enters wiki maintenance and can
  re-trigger headless authoring → another ``claude -p`` → ``SessionEnd`` →
  … an unbounded fork loop. :mod:`consolidate_background` is the same vector.
* **Pollution.** ``PostToolUse`` capture (:mod:`post_tool_capture`) would
  record the authoring agent's own ``Read``/``Grep`` calls as memories;
  ``UserPromptSubmit``/``SessionStart`` hooks (:mod:`auto_recall`,
  :mod:`session_start`) would inject context the authoring agent never asked
  for; ``SubagentStart`` briefing (:mod:`agent_briefing`) would fire for every
  spawned specialist.

The worker marks its child environment with
``CORTEX_HEADLESS_AUTHORING_CHILD=1`` (see
``headless_authoring._subprocess_env``). Every Cortex hook calls
:func:`exit_if_headless_authoring_child` at its process entry point; in the
marked child it exits ``0`` immediately — a silent no-op that lets the
``claude -p`` call proceed with no side effects. Everywhere else it does
nothing.

This module has zero dependencies beyond the standard library, so importing it
from a hook can never fail for a missing third-party package.
"""

from __future__ import annotations

import os
import sys

# The worker stamps this into the authoring child's env. Value "1" means
# "you are the headless authoring subprocess — do no hook work".
_HEADLESS_CHILD_FLAG = "CORTEX_HEADLESS_AUTHORING_CHILD"


def is_headless_authoring_child() -> bool:
    """True when running inside the headless wiki-authoring subprocess."""
    return os.environ.get(_HEADLESS_CHILD_FLAG) == "1"


def exit_if_headless_authoring_child() -> None:
    """Exit ``0`` immediately when inside the headless authoring child.

    A no-op in every other context. Called at the top of each Cortex hook's
    process entry point so the hook does no work — preventing the recursion
    and memory pollution documented in this module's docstring — while the
    ``claude -p`` authoring drain runs.
    """
    if is_headless_authoring_child():
        sys.exit(0)
