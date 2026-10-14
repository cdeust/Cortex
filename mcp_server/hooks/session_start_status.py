"""The line a user sees when a session starts: "Cortex ready", or why not.

Claude Code shows a SessionStart hook's plain stdout to Claude only; the user
sees the hook's JSON ``systemMessage``. So the hook's whole output becomes one
JSON object: the context it always printed goes to
``hookSpecificOutput.additionalContext`` unchanged, and one status line goes
to ``systemMessage`` — "Cortex ready" only when the memory store answered,
with where memories live and whether recall is semantic or keyword-only while
semantic search installs (the launcher passes that state,
``scripts/launcher_ml.py``). Anything else is "Cortex not ready" with the
real cause.

source: docs/adr/ADR-1104-zero-ops-plugin-install.md
"""

from __future__ import annotations

import contextlib
import io
import json
import os
from typing import Callable, Mapping

READY = "Cortex ready"  # source: ADR-1104 (the owner's acceptance string)
NOT_READY = "Cortex not ready"  # source: ADR-1104


def semantic_clause(environ: Mapping[str, str]) -> str:
    """How recall ranks right now, as the launcher found it."""
    state = environ.get("CORTEX_SEMANTIC_SEARCH", "")
    if state == "installing":
        return (
            "semantic search is installing in the background, "
            "keyword recall until it finishes"
        )
    if state == "failed":
        detail = environ.get("CORTEX_SEMANTIC_SEARCH_DETAIL", "")
        return f"keyword recall only, semantic search install failed: {detail}"
    if state == "ready":
        return "semantic search on"
    return "semantic search state unknown (not started by the plugin launcher)"


def ready(store: str, memories: int, environ: Mapping[str, str] = os.environ) -> str:
    noun = "memory" if memories == 1 else "memories"
    return f"{READY}: {store}, {memories} {noun}; {semantic_clause(environ)}."


def not_ready(cause: str) -> str:
    return f"{NOT_READY}: {cause}"


def run_and_report(main: Callable[[], str]) -> None:
    """Run ``main`` (it prints context, returns the status line); emit one JSON.

    Postcondition: stdout holds exactly one JSON object whose
    ``systemMessage`` is ``main``'s status line. An exception in ``main``
    still propagates after its status reaches the user as "not ready".
    """
    captured = io.StringIO()
    status = not_ready("the SessionStart hook stopped before reporting")
    try:
        with contextlib.redirect_stdout(captured):
            status = main()
    except BaseException as exc:
        if not isinstance(exc, SystemExit) or exc.code not in (0, None):
            status = not_ready(f"{type(exc).__name__}: {exc}")
        raise
    finally:
        print(
            json.dumps(
                {
                    "systemMessage": status,
                    "hookSpecificOutput": {
                        "hookEventName": "SessionStart",
                        "additionalContext": captured.getvalue(),
                    },
                }
            )
        )
