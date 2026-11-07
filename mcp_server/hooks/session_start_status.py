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


ZERO_DOWNLOAD_ENV = "CORTEX_EMBEDDING_ZERO_DOWNLOAD"  # source: ADR-0519


def _without_launcher(environ: Mapping[str, str]) -> tuple[str, str]:
    """The state when no plugin launcher reported one (the Codex entry, a
    direct ``python -m`` run): the same opt-out rule, else the distribution."""
    from importlib.metadata import PackageNotFoundError, version  # noqa: PLC0415 — metadata only, never the ML stack

    if environ.get(ZERO_DOWNLOAD_ENV, "").lower() in ("1", "true"):
        return "off", f"{ZERO_DOWNLOAD_ENV} is set"
    try:
        version("sentence-transformers")
    except PackageNotFoundError:
        return "off", "sentence-transformers is not in this install"
    return "ready", ""


def semantic_clause(environ: Mapping[str, str]) -> str:
    """How recall ranks right now, as the launcher found it."""
    state = environ.get("CORTEX_SEMANTIC_SEARCH", "")
    detail = environ.get("CORTEX_SEMANTIC_SEARCH_DETAIL", "")
    if not state:
        state, detail = _without_launcher(environ)
    if state == "installing":
        return (
            "semantic search is installing in the background, "
            "keyword recall until it finishes"
        )
    if state == "failed":
        return f"keyword recall only, semantic search install failed: {detail}"
    if state == "ready":
        return "semantic search on"
    return f"keyword recall only, semantic search not installed: {detail}"


def ready(store: str, memories: int, environ: Mapping[str, str] = os.environ) -> str:
    noun = "memory" if memories == 1 else "memories"
    return f"{READY}: {store}, {memories} {noun}; {semantic_clause(environ)}."


FALLBACK_ENV = "CORTEX_SQLITE_FALLBACK"  # source: ADR-1114 D3 (set by the launcher)


def sqlite_ready(
    store: str, memories: int, environ: Mapping[str, str] = os.environ
) -> str:
    """``ready`` for the SQLite store, plus one line naming why it is the
    SQLite fallback when Setup could not run the managed server (ADR-1114 D3)."""
    line = ready(store, memories, environ)
    cause = environ.get(FALLBACK_ENV, "").strip()
    return f"{line}\nSQLite fallback: {cause}" if cause else line


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
                },
                ensure_ascii=False,  # stdout is strict UTF-8 (ADR-1098)
            )
        )


def home_relative(path: str) -> str:
    """``~/...`` for a path under the home directory, else the path."""
    home = os.path.expanduser("~")
    return "~" + path[len(home) :] if path.startswith(home + os.sep) else path
