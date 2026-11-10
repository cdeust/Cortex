"""Which domain a memory write may target from this session (GHSA-7848-qh48-mx2w).

`remember` and the other writing tools take a caller-supplied `directory` or
`domain`. A caller steered by untrusted content could place text in another local
project's domain, and that project's `query_methodology` would serve it as hot
memory: a cross-project prompt-injection primitive. A write may target:

- no domain, or a shared domain that names no known repository (`documents`,
  `prd`, a team name): memory is meant to be shared across domains;
- the domain of the session's own project (`CLAUDE_PROJECT_DIR`, else the server's
  working directory);
- another project's domain only when the user allows it in the local environment,
  `CORTEX_CROSS_PROJECT_WRITES=<domain>,<domain>` or `*`. A tool argument cannot
  open it: the caller is the party the rule guards against.

Anything else fails with the variable to set, never a silent redirect.

The domain is one of two channels. The SessionStart and auto-recall hooks select
by `directory_context`: a memory is served to a session whose project root is
that directory or lies below it (`shared.project_scope`). So the directory a
write stores, and the one an existing row carries, pass the same rule
(`require_writable_directory`): it must reach no project but the session's.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import NoReturn

from mcp_server.errors import ValidationError
from mcp_server.shared.domain_mapping import (
    project_domains,
    project_roots,
    resolve_cwd,
    resolve_explicit_domain,
)
from mcp_server.shared.project_scope import memory_matches_project, project_ancestors

# source: the owner decision of 2026-11-07 on GHSA-7848: a local variable may reopen
# cross-project writes, a tool parameter may not.
ALLOW_ENV = "CORTEX_CROSS_PROJECT_WRITES"
# source: Claude Code sets it to the open project for MCP servers (GHSA-gvpp-v77h-5w8g).
SESSION_ENV = "CLAUDE_PROJECT_DIR"
# source: the same owner decision; the allowance value that names every project. A
# global memory reaches every project's hot memories (`domain = ? OR is_global`), so
# writing one, or changing an existing one, needs it.
EVERY_PROJECT = "*"
# source: shared.project_scope.memory_matches_project, its `is_global` argument. The
# directory rule asks about a project-scoped memory; a global one is refused before.
_LOCAL = False


def session_domain(environ: Mapping[str, str] = os.environ) -> str:
    """The domain of the project this server session runs in, or ''."""
    return resolve_cwd(environ.get(SESSION_ENV) or os.getcwd())


def _allowed(environ: Mapping[str, str]) -> frozenset[str]:
    raw = environ.get(ALLOW_ENV, "")
    return frozenset(d.strip().lower() for d in raw.split(",") if d.strip())


def _refused_domain(target: str, environ: Mapping[str, str]) -> tuple[str, str] | None:
    """(target, session) when the canonical `target` is another project's domain.

    `target` is a domain identity already: resolved from a path, read from a stored
    row, or resolved once from a name the caller gave. It is never resolved again
    here. A directory name can be an alias of one project and the canonical of
    another repository family; resolving a canonical a second time would turn that
    family's domain into the aliased project, refuse the family its own writes and
    let the aliased project change the family's rows.
    """
    if not target or target not in project_domains():
        return None
    session = session_domain(environ)
    allowed = _allowed(environ)
    if target == session or EVERY_PROJECT in allowed or target in allowed:
        return None
    return target, session


def require_writable_domain(
    domain: str, tool: str, environ: Mapping[str, str] = os.environ
) -> str:
    """The domain the write must store; ValidationError when it is another project's.

    The check reads the resolved domain, so the caller stores that one, never the
    raw argument: a name that resolves to the session's own project (a directory
    name, a family member) can also be another family's canonical, and rows stored
    under the raw name would reach that family's hot memories. A name that is itself
    a project's domain is that domain, whatever alias it also carries: it is refused
    from another project, never redirected to the session's. A name that resolves
    to no known project is a shared domain and is returned as given.
    """
    name = (domain or "").strip().lower()
    target = name if name in project_domains() else resolve_explicit_domain(name)
    if _refused_domain(target, environ) is not None:
        _refuse(target, tool, environ)
    return target if target in project_domains() else (domain or "")


def require_writable_canonical(
    domain: str, tool: str, environ: Mapping[str, str] = os.environ
) -> None:
    """Raise ValidationError when the already resolved `domain` is another project's.

    For a domain that is an identity already (resolved from a path by `remember` or
    `seed_project`, or stored on a row): it is compared as it is, never resolved
    through the name aliases a second time (see `_refused_domain`).
    """
    target = (domain or "").strip().lower()
    if _refused_domain(target, environ) is not None:
        _refuse(target, tool, environ)


def _refuse(target: str, tool: str, environ: Mapping[str, str]) -> NoReturn:
    """Raise the refusal of a write into `target`, another project's domain."""
    session = session_domain(environ)
    where = f"this session's project ({session!r})" if session else "no known project"
    raise ValidationError(
        f"{tool}: domain {target!r} belongs to another project than {where}; "
        f"set {ALLOW_ENV}={target} (or '*') in the environment to allow it",
        {"tool": tool, "field": "domain", "domain": target, "session": session},
    )


def session_directory(environ: Mapping[str, str] = os.environ) -> str:
    """The directory of the project this server session runs in."""
    return environ.get(SESSION_ENV) or os.getcwd()


def _reached_projects(directory: str | None) -> frozenset[str]:
    """Domains of the known projects whose sessions are served `directory`'s memories.

    The rule is the hooks' own (`shared.project_scope`): a memory is served to a
    session whose project root is its directory or lies below it. So a project is
    reached when `directory` is one of its roots or a folder above one, or lies
    inside one (a session opened below the root). The hooks compare path text, and
    a parent of the projects can be a symlink: `directory` is compared as the hooks
    read it and as resolved, with each root in both forms too.
    """
    # The text the hooks compare: separators normalised, no trailing one, and no
    # character trimmed (a folder name may end with a space). A relative directory,
    # a label such as `run:<id>` or `/` is served to no session.
    ancestors = project_ancestors(directory)
    if not ancestors or not Path(ancestors[0]).is_absolute():
        return frozenset()
    forms = {ancestors[0], Path(ancestors[0]).resolve().as_posix()}
    return frozenset(
        domain
        for root, domain in project_roots().items()
        for form in forms
        if memory_matches_project(form, _LOCAL, root) or root in project_ancestors(form)
    )


def _refused_directory(directory: str | None, environ: Mapping[str, str]) -> str | None:
    """A project `directory` reaches that this session may not write into, or None."""
    allowed = _allowed(environ)
    reached = _reached_projects(directory) - allowed
    if not reached or EVERY_PROJECT in allowed:
        return None
    others = reached - {session_domain(environ)}
    return min(others) if others else None


def require_writable_directory(
    directory: str | None, tool: str, environ: Mapping[str, str] = os.environ
) -> None:
    """Raise ValidationError when `directory`'s memories reach another project."""
    other = _refused_directory(directory, environ)
    if other is None:
        return
    session = session_domain(environ)
    where = f"this session's project ({session!r})" if session else "no known project"
    raise ValidationError(
        f"{tool}: a memory stored under directory {directory!r} is served to project "
        f"{other!r}, another project than {where}; set {ALLOW_ENV}={other} (or '*') "
        "in the environment to allow it",
        {"tool": tool, "field": "directory", "domain": other, "session": session},
    )


def require_stable_domain(domain: str, written: str, tool: str) -> None:
    """Raise ValidationError when a resolved `domain` resolves again to `written`."""
    if written == domain:
        return
    raise ValidationError(
        f"{tool}: domain {domain!r} is also an alias of {written!r}, the domain the "
        "files would be written under; run it from a directory inside the project",
        {"tool": tool, "field": "domain", "domain": written},
    )


# source: GHSA-7848-qh48-mx2w; the reason a detected global scope stayed local.
KEPT_LOCAL = f"global scope detected but {ALLOW_ENV}=* is not set; kept local"


def _every_project(environ: Mapping[str, str]) -> bool:
    return EVERY_PROJECT in _allowed(environ)


def require_global_allowed(tool: str, environ: Mapping[str, str] = os.environ) -> None:
    """Raise ValidationError unless the user allows writes into every project."""
    if not _every_project(environ):
        raise ValidationError(
            f"{tool}: is_global=true writes into every project's memory; "
            f"set {ALLOW_ENV}={EVERY_PROJECT} in the environment to allow it",
            {"tool": tool, "field": "is_global"},
        )


def global_scope(
    scope: tuple[bool, str],
    explicit: bool,
    tool: str,
    environ: Mapping[str, str] = os.environ,
) -> tuple[bool, str]:
    """The (is_global, reason) a write may keep; an explicit request is refused."""
    is_global, reason = scope
    if not is_global or _every_project(environ):
        return is_global, reason
    if explicit:
        require_global_allowed(tool, environ)
    return False, KEPT_LOCAL


def require_writable_memory(
    row: Mapping, tool: str, environ: Mapping[str, str] = os.environ
) -> None:
    """Raise ValidationError when this session may not change the memory ``row``."""
    if row.get("is_global") and not _every_project(environ):
        raise ValidationError(
            f"{tool}: memory {row.get('id')} is global, so changing it reaches every "
            f"project; set {ALLOW_ENV}={EVERY_PROJECT} in the environment to allow it",
            {"tool": tool, "field": "memory_id", "memory_id": row.get("id")},
        )
    require_writable_canonical(row.get("domain") or "", tool, environ)
    require_writable_directory(row.get("directory_context"), tool, environ)


def memory_writable(row: Mapping, environ: Mapping[str, str] = os.environ) -> bool:
    """Whether a write may pick ``row`` as its target (merge, replica refresh)."""
    if row.get("is_global") and not _every_project(environ):
        return False
    target = (row.get("domain") or "").strip().lower()
    if _refused_domain(target, environ) is not None:
        return False
    return _refused_directory(row.get("directory_context"), environ) is None
