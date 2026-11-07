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
from mcp_server.shared.domain_mapping import project_domains, resolve_cwd

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


def require_writable_domain(
    domain: str, tool: str, environ: Mapping[str, str] = os.environ
) -> None:
    """Raise ValidationError when `domain` is another project's than the session's."""
    target = (domain or "").strip().lower()
    if not target or target not in project_domains():
        return
    session = session_domain(environ)
    allowed = _allowed(environ)
    if target == session or "*" in allowed or target in allowed:
        return
    where = f"this session's project ({session!r})" if session else "no known project"
    raise ValidationError(
        f"{tool}: domain {target!r} belongs to another project than {where}; "
        f"set {ALLOW_ENV}={target} (or '*') in the environment to allow it",
        {"tool": tool, "field": "domain", "domain": target, "session": session},
    )
