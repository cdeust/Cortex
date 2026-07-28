"""Bootstrap entry point for the methodology-agent MCP server.

Uses FastMCP (3.x) for protocol handling — supports MCP 2025-11-25 natively.
Bridges existing async handler functions as FastMCP tools.

Usage:
    python -m mcp_server
"""

from __future__ import annotations

import signal
import sys

# Eager-import scipy/sklearn (pulled in transitively by ``sentence_transformers``,
# a mandatory dependency — see pyproject.toml) on the main thread, before the
# FastMCP event loop exists. embedding_engine._ensure_model() lazily does
# ``from sentence_transformers import SentenceTransformer`` on first
# embed/encode call; on Windows, that first import of scipy/sklearn's C
# extensions can deadlock CPython's import lock when it runs inside a
# FastMCP/anyio worker thread instead of the main thread — the worker never
# recovers, and every subsequent write (remember) hangs identically since
# the import lock stays held. Importing here first makes the worker-thread
# import a no-op sys.modules lookup. Cost: ~1.6s on a cold disk/page cache
# (measured on macOS, `python -c "import scipy.linalg, scipy.special,
# sklearn.utils, sklearn.utils.validation"` in isolation, first touch this
# session), dropping to near-zero once the OS has these .so/.pyc files
# cached — pays once per fresh boot, not once per server restart.
# source: cdeust/Cortex#92 (rapporteur mbe14, validated fix, Windows 11,
# Python 3.13.13, reproduced on FastMCP 3.2.4 and 3.4.4).
try:  # pragma: no cover — defensive; sentence-transformers is mandatory
    # (pyproject.toml), so these transitive imports are expected to exist,
    # but a degraded/partial install must not prevent server startup.
    import scipy.linalg  # noqa: F401
    import scipy.special  # noqa: F401
    import sklearn.utils  # noqa: F401
    import sklearn.utils.validation  # noqa: F401
except Exception as _preload_exc:
    # Degraded install: the lazy import inside embedding_engine will fail
    # loudly on first use; here we only lose the deadlock-avoidance preload.
    print(
        f"[cortex] scipy/sklearn preload failed (startup continues): {_preload_exc}",
        file=sys.stderr,
    )

from fastmcp import FastMCP

from mcp_server import (
    mcp_prompts,
    tool_profiles,
    tool_registry_advanced,
    tool_registry_core,
    tool_registry_ingest,
    tool_registry_manage,
    tool_registry_memory,
    tool_registry_nav,
    tool_registry_wiki,
)
from mcp_server.core import telemetry
from mcp_server.tool_profile_middleware import ToolProfileMiddleware
from mcp_server.core.wiki_axis_registry import configure_default_wiki_root
from mcp_server.core.wiki_classifier import configure_user_rules_provider
from mcp_server.handlers._tool_meta import apply_param_docs
from mcp_server.infrastructure.config import WIKI_ROOT
from mcp_server.infrastructure.mcp_client_pool import close_all
from mcp_server.infrastructure.otel_exporter import build_otel_exporter
from mcp_server.infrastructure.upstream_availability import (
    codebase_upstream_available,
    prd_upstream_available,
)
from mcp_server.infrastructure.wiki_schema_reader import load_registry

# ── Reverse-DI wiring (issue #126) ──────────────────────────────────────────
#
# core/wiki_axis_registry.py and core/wiki_classifier.py declare what they
# need (a wiki-root provider / a user-rules provider) rather than importing
# infrastructure directly. This is the one place — the composition root —
# that supplies the real, infrastructure-backed values.

configure_default_wiki_root(lambda: WIKI_ROOT)
configure_user_rules_provider(lambda: load_registry(WIKI_ROOT).rules)

# Optional OTLP telemetry export (issue #122) -- OFF by default. Wiring the
# concrete exporter into the core port happens only here, in the
# composition root; core/telemetry.py never imports infrastructure.
# build_otel_exporter() returns None (no-op) unless the operator set
# OTEL_EXPORTER_OTLP_ENDPOINT, so this line is a zero-behavior-change no-op
# for every existing deployment.
telemetry.set_exporter(build_otel_exporter())

# ── Active tool profile (issue #177) ───────────────────────────────────────
#
# Resolved once at startup from --profile / CORTEX_MCP_PROFILE, defaulting to
# FULL. The default stays FULL because shrinking the advertised surface is a
# breaking change (a client that called a now-hidden tool breaks) — this
# diverges from #177 criterion 2 and is recorded in CHANGELOG.md, mirroring
# automatised-pipeline's ToolProfile reasoning.
ACTIVE_PROFILE = tool_profiles.resolve()

# ── Server Instance ────────────────────────────────────────────────────────

mcp = FastMCP(
    name="methodology-agent",
    version="1.0.0",
    # Per-profile instructions: the server describes itself in the shape it was
    # started in (issue #177 criterion 3). FULL keeps the historical onboarding
    # line ("Call query_methodology…").
    instructions=tool_profiles.instructions(ACTIVE_PROFILE),
)

# ── Tool Registration ──────────────────────────────────────────────────────


def merged_schemas() -> dict[str, dict]:
    """The tool-name → handler-schema map, merged across every registry.

    Single source of truth for both ``apply_param_docs`` (client-visible
    parameter docs) and ``mcp_prompts`` (prompt step summaries), so a prompt's
    description of a tool cannot drift from the tool's own schema (#176
    criterion 3, the #98 drift class).
    """
    return {
        **tool_registry_core.SCHEMAS,
        **tool_registry_memory.SCHEMAS,
        **tool_registry_manage.SCHEMAS,
        **tool_registry_nav.SCHEMAS,
        **tool_registry_advanced.SCHEMAS,
        **tool_registry_wiki.SCHEMAS,
        **tool_registry_ingest.SCHEMAS,
    }


def register_all(mcp: FastMCP, *, codebase: bool, prd: bool) -> None:
    """Wire every tool registry onto ``mcp``.

    The 50 standalone tools always register (ground truth:
    ``tests_py/test_main.py::test_standalone_baseline_is_50_tools`` — the 49
    re-verified 2026-07-12 by a live DB-less stdio `tools/list` round-trip
    on `bare-container-contract`, plus ``wiki_migrate`` (FS→PG wiki parity);
    see CLAUDE.md handlers/ section for the per-tier breakdown). The 3
    upstream-integration tools
    register only when their upstream MCP server is available — ``codebase``
    gates ingest_codebase + change_impact (automatised-pipeline), ``prd`` gates
    ingest_prd (prd-spec-generator). source: MCP Directory decision 2026-06-19.
    """
    tool_registry_core.register(mcp)
    tool_registry_memory.register(mcp)
    tool_registry_manage.register(mcp)
    tool_registry_nav.register(mcp)
    tool_registry_advanced.register(mcp)
    tool_registry_wiki.register(mcp)
    tool_registry_ingest.register(mcp, codebase=codebase, prd=prd)
    # FastMCP derives input schemas from function signatures; project the
    # hand-written inputSchema parameter descriptions onto them so clients
    # (and registry graders) see documented parameters.
    apply_param_docs(mcp, merged_schemas())


register_all(
    mcp,
    codebase=codebase_upstream_available(),
    prd=prd_upstream_available(),
)

# ── Prompts + profile enforcement (issues #176, #177) ───────────────────────
#
# Prompts render their step summaries from the same schema map as tools/list
# (no drift). ToolProfileMiddleware filters the advertised tool/prompt surface
# to ACTIVE_PROFILE and REJECTS calls to tools the profile excludes — hiding a
# destructive tool while still executing it on call would be a security hole,
# not a token optimisation (#177 criterion 5). Under the default FULL profile
# the middleware is a pass-through, so existing behaviour is unchanged.
mcp_prompts.register_prompts(mcp, merged_schemas())
mcp.add_middleware(ToolProfileMiddleware(ACTIVE_PROFILE))

# resources/list interop shim (#176 criterion 4): FastMCP 3.2.4 already answers
# resources/list and resources/templates/list with empty arrays and declares
# the capability, so the -32601 failure some clients surface on connect
# (CBM upstream #958) does not occur here — the framework provides the shim.
# Verified 2026-07-25 by an in-memory Client round-trip:
#   list_resources() -> []   list_resource_templates() -> []
# No code is needed; recorded here per §8 rather than left implicit.

# ── Lifecycle ──────────────────────────────────────────────────────────────


def _shutdown(sig=None, frame=None) -> None:
    close_all()
    sys.exit(0)


def main() -> None:
    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
