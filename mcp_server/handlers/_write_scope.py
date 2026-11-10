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
"""

from __future__ import annotations

import os
from collections.abc import Mapping

from mcp_server.errors import ValidationError
from mcp_server.shared.domain_mapping import (
    project_domains,
    resolve_cwd,
    resolve_explicit_domain,
)

# source: the owner decision of 2026-11-07 on GHSA-7848: a local variable may reopen
# cross-project writes, a tool parameter may not.
ALLOW_ENV = "CORTEX_CROSS_PROJECT_WRITES"
# source: Claude Code sets it to the open project for MCP servers (GHSA-gvpp-v77h-5w8g).
SESSION_ENV = "CLAUDE_PROJECT_DIR"


def session_domain(environ: Mapping[str, str] = os.environ) -> str:
    """The domain of the project this server session runs in, or ''."""
    return resolve_cwd(environ.get(SESSION_ENV) or os.getcwd())


def _allowed(environ: Mapping[str, str]) -> frozenset[str]:
    raw = environ.get(ALLOW_ENV, "")
    return frozenset(d.strip().lower() for d in raw.split(",") if d.strip())


def _refused_domain(domain: str, environ: Mapping[str, str]) -> tuple[str, str] | None:
    """(target, session) when `domain` is another project's than the session's."""
    target = resolve_explicit_domain(domain or "")
    if not target or target not in project_domains():
        return None
    session = session_domain(environ)
    allowed = _allowed(environ)
    if target == session or "*" in allowed or target in allowed:
        return None
    return target, session


def require_writable_domain(
    domain: str, tool: str, environ: Mapping[str, str] = os.environ
) -> str:
    """The domain the write must store; ValidationError when it is another project's.

    The check reads the resolved domain, so the caller stores that one, never the
    raw argument: a name that resolves to the session's own project (a directory
    name, a family member) can also be another family's canonical, and rows stored
    under the raw name would reach that family's hot memories. A name that resolves
    to no known project is a shared domain and is returned as given.
    """
    refused = _refused_domain(domain, environ)
    if refused is None:
        target = resolve_explicit_domain(domain or "")
        return target if target in project_domains() else (domain or "")
    target, session = refused
    where = f"this session's project ({session!r})" if session else "no known project"
    raise ValidationError(
        f"{tool}: domain {target!r} belongs to another project than {where}; "
        f"set {ALLOW_ENV}={target} (or '*') in the environment to allow it",
        {"tool": tool, "field": "domain", "domain": target, "session": session},
    )


# A global memory reaches every project's hot memories (`domain = ? OR is_global`),
# so writing one, or changing an existing one, needs the allowance for every project.
EVERY_PROJECT = "*"
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
    require_writable_domain(row.get("domain") or "", tool, environ)


def memory_writable(row: Mapping, environ: Mapping[str, str] = os.environ) -> bool:
    """Whether a write may pick ``row`` as its target (merge, replica refresh)."""
    if row.get("is_global") and not _every_project(environ):
        return False
    return _refused_domain(row.get("domain") or "", environ) is None
