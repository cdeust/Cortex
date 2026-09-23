"""Project-scope predicate for the context-injecting hooks.

Issue #604: session_start and auto_recall queried memories with no
project predicate, so a session under one project received the hot and
protected memories of every other project. This module is the one place
that decides whether a memory belongs on a given session, so both hooks
and both storage backends (PostgreSQL raw SQL, SQLite store rows) apply
the identical rule instead of four drifting copies of it.

Rule (owner decision, ADR number 1080): a memory is injected when its
``directory_context`` equals the session's project root, or is an
ancestor of it, or the memory is global. An empty ``directory_context``
is not a wildcard -- it never matches a concrete project root.
"""

from __future__ import annotations

from collections.abc import Mapping


def resolve_project_root(
    event: Mapping[str, object], env: Mapping[str, str]
) -> str | None:
    """The session's project root, or None when neither source has one.

    Precondition: event is the parsed hook JSON (may lack "cwd"); env is
    the process environment, or a substitute mapping in tests.
    Postcondition: returns CLAUDE_PROJECT_ROOT when set and non-empty
    (the override the hooks already honour); otherwise the event's
    "cwd" when it is a non-empty string; otherwise None. A None result
    is not a fallback to a filesystem cwd() call -- callers that cannot
    resolve a project root must restrict injection to global memories
    and log that they did, never inject everything (issue #604).
    """
    override = env.get("CLAUDE_PROJECT_ROOT")
    if override:
        return override
    cwd = event.get("cwd")
    return cwd if isinstance(cwd, str) and cwd else None


def _normalize_path(path: str) -> str:
    """Slash-normalize and drop a trailing separator for comparison."""
    return path.replace("\\", "/").rstrip("/")


def project_ancestors(project_root: str | None) -> list[str]:
    """project_root and every directory above it, most specific first.

    Pure path-component walk, no filesystem access. Ingestion resolves paths,
    but explicit remember writes preserve the supplied directory, including
    aliases (remember_helpers._build_insert_record). Readers must preserve
    that same project identity instead of resolving only the query path.

    Postcondition: None or "" yields [] -- the caller-facing contract a
    query-scoping caller relies on: pass this list straight to a
    directory_ancestors parameter, and an unresolved project_root reduces
    the query to is_global-only without a separate branch at the call
    site (issue #604 follow-up).
    """
    if not project_root:
        return []
    normalized = _normalize_path(project_root)
    if not normalized:
        return []
    parts = normalized.split("/")
    # range stops at 2, not 0: parts[:1] on a leading-slash path is [""],
    # a non-empty list whose join is "" -- an empty ancestor would let an
    # empty directory_context match every project downstream (a caller
    # builds "directory_context = ANY(ancestors)"/"IN (ancestors)" SQL
    # straight from this list, with no separate empty-string guard).
    return ["/".join(parts[:i]) for i in range(len(parts), 1, -1)]


def memory_matches_project(
    directory_context: str | None,
    is_global: bool,
    project_root: str | None,
) -> bool:
    """True when this memory belongs on a session rooted at project_root.

    Precondition: directory_context is a memory's raw column value (may
    be None or "" for memories written before directory scoping, or for
    genuinely-global memories); project_root is resolve_project_root's
    result for the current session.
    Postcondition: global memories always match. A non-global memory
    matches only when project_root is known AND directory_context is
    project_root or one of its ancestors. An empty directory_context
    never matches -- it is not a wildcard for "every project".
    """
    if is_global:
        return True
    if not directory_context or not project_root:
        return False
    return _normalize_path(directory_context) in project_ancestors(project_root)
