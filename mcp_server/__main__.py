"""Bootstrap entry point for the methodology-agent MCP server.

Uses the ``mcp`` SDK's native ``MCPServer`` (2.0.0+) for protocol handling.
Bridges existing async handler functions as MCP tools. mcp 2.0.0 folded
FastMCP's decorator API into the SDK itself (``mcp.server.mcpserver
.MCPServer``, the documented successor to ``fastmcp.FastMCP``); this module
was fastmcp-based before that migration (see git history + issue: PR #331,
mcp 1.29.0 -> 2.0.0).

Usage:
    python -m mcp_server
"""

from __future__ import annotations

import signal
import sys

# Eager-import scipy/sklearn (pulled in transitively by ``sentence_transformers``,
# a mandatory dependency — see pyproject.toml) on the main thread, before the
# MCP server's event loop exists. embedding_engine._ensure_model() lazily does
# ``from sentence_transformers import SentenceTransformer`` on first
# embed/encode call; on Windows, that first import of scipy/sklearn's C
# extensions can deadlock CPython's import lock when it runs inside an
# anyio worker thread instead of the main thread — the worker never
# recovers, and every subsequent write (remember) hangs identically since
# the import lock stays held. Importing here first makes the worker-thread
# import a no-op sys.modules lookup. Cost: ~1.6s on a cold disk/page cache
# (measured on macOS, `python -c "import scipy.linalg, scipy.special,
# sklearn.utils, sklearn.utils.validation"` in isolation, first touch this
# session), dropping to near-zero once the OS has these .so/.pyc files
# cached — pays once per fresh boot, not once per server restart.
# source: cdeust/Cortex#92 (rapporteur mbe14, validated fix, Windows 11,
# Python 3.13.13, reproduced on FastMCP 3.2.4 and 3.4.4 — the underlying
# thread-vs-import-lock hazard is a CPython property, not FastMCP-specific,
# so the mcp 2.0.0 migration does not remove the need for this preload).
try:  # pragma: no cover — defensive; sentence-transformers is mandatory
    # (pyproject.toml), so these transitive imports are expected to exist,
    # but a degraded/partial install must not prevent server startup.
    import scipy.linalg  # noqa: F401
    import scipy.special  # noqa: F401
    import sklearn.utils  # noqa: F401
    import sklearn.utils.validation  # noqa: F401
except Exception as _preload_exc:  # noqa: BLE001 — failure is reported to stderr; execution degrades, never crashes
    # Degraded install: the lazy import inside embedding_engine will fail
    # loudly on first use; here we only lose the deadlock-avoidance preload.
    print(
        f"[cortex] scipy/sklearn preload failed (startup continues): {_preload_exc}",
        file=sys.stderr,
    )

import anyio
from mcp.server.mcpserver import MCPServer

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
from mcp_server.handlers._tool_meta import apply_output_schemas, apply_param_docs
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
# ai-architect-mcp-codebase's ToolProfile reasoning.
ACTIVE_PROFILE = tool_profiles.resolve()

# ── Server Instance ────────────────────────────────────────────────────────
#
# ToolProfileMiddleware must be constructed and passed here, at
# MCPServer.__init__: mcp 2.0.0's ``middleware`` list is a constructor-only
# parameter (no post-construction ``add_middleware`` exists, unlike
# FastMCP). Registering tools/prompts onto ``mcp`` after this point is still
# safe — the middleware inspects the runtime call/list dispatch, not the
# registration-time tool set.

mcp = MCPServer(
    name="methodology-agent",
    version="1.0.0",
    # Per-profile instructions: the server describes itself in the shape it was
    # started in (issue #177 criterion 3). FULL keeps the historical onboarding
    # line ("Call query_methodology…").
    instructions=tool_profiles.instructions(ACTIVE_PROFILE),
    middleware=[ToolProfileMiddleware(ACTIVE_PROFILE)],
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


def register_all(mcp: MCPServer, *, codebase: bool, prd: bool) -> None:
    """Wire every tool registry onto ``mcp``.

    The 50 standalone tools always register (ground truth:
    ``tests_py/test_main.py::test_standalone_baseline_is_50_tools`` — the 49
    re-verified 2026-07-12 by a live DB-less stdio `tools/list` round-trip
    on `bare-container-contract`, plus ``wiki_migrate`` (FS→PG wiki parity);
    see CLAUDE.md handlers/ section for the per-tier breakdown). The 3
    upstream-integration tools
    register only when their upstream MCP server is available — ``codebase``
    gates ingest_codebase + change_impact (ai-architect-mcp-codebase), ``prd`` gates
    ingest_prd (prd-spec-generator). source: MCP Directory decision 2026-06-19.
    """
    tool_registry_core.register(mcp)
    tool_registry_memory.register(mcp)
    tool_registry_manage.register(mcp)
    tool_registry_nav.register(mcp)
    tool_registry_advanced.register(mcp)
    tool_registry_wiki.register(mcp)
    tool_registry_ingest.register(mcp, codebase=codebase, prd=prd)
    # MCPServer derives input AND output schemas from the function signature
    # alone (return type for output; mcp 2.0.0 has no way to pass a raw
    # output JSON Schema at registration time). Project the hand-written
    # inputSchema parameter descriptions and outputSchema shapes onto the
    # registered tools so clients (and registry graders) see them.
    apply_param_docs(mcp, merged_schemas())
    apply_output_schemas(mcp, merged_schemas())


register_all(
    mcp,
    codebase=codebase_upstream_available(),
    prd=prd_upstream_available(),
)

# ── Prompts + profile enforcement (issues #176, #177) ───────────────────────
#
# Prompts render their step summaries from the same schema map as tools/list
# (no drift). ToolProfileMiddleware (constructed into ``mcp`` above, at
# MCPServer.__init__ time) filters the advertised tool/prompt surface to
# ACTIVE_PROFILE and REJECTS calls to tools the profile excludes — hiding a
# destructive tool while still executing it on call would be a security hole,
# not a token optimisation (#177 criterion 5). Under the default FULL profile
# the middleware is a pass-through, so existing behaviour is unchanged.
mcp_prompts.register_prompts(mcp, merged_schemas())

# resources/list interop shim (#176 criterion 4): the MCP SDK already answers
# resources/list and resources/templates/list with empty arrays and declares
# the capability, so the -32601 failure some clients surface on connect
# (CBM upstream #958) does not occur here — the framework provides the shim.
# Verified 2026-07-25 by an in-memory Client round-trip (FastMCP 3.2.4;
# unchanged in the mcp 2.0.0 rewrite this module now runs on top of):
#   list_resources() -> []   list_resource_templates() -> []
# No code is needed; recorded here per §8 rather than left implicit.

# ── Lifecycle ──────────────────────────────────────────────────────────────


def _shutdown(sig=None, frame=None) -> None:
    close_all()
    sys.exit(0)


def main() -> None:
    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)
    # Was mcp_server.infrastructure.stdio_transport.run_stdio_drained, a
    # hand-built workaround for a FastMCP 3.4.5 defect: its LowLevelServer
    # .run override dropped the base SDK's own `finally:
    # tg.cancel_scope.cancel()`, so on stdin EOF the write stream could
    # close before an in-flight request's handler (dispatched from the same
    # input batch) had a chance to respond. mcp 2.0.0 removed FastMCP as a
    # wrapping layer and rewrote the dispatcher
    # (mcp.shared.jsonrpc_dispatcher.JSONRPCDispatcher.run) with the
    # join-before-close invariant built in and explicitly documented ("the
    # write stream closes only after the task-group join, so teardown
    # writes still land") -- confirmed by direct reproduction of
    # stdio_transport.py's own characterization scenario (deterministic
    # handler_started/handler_may_finish/write_stream_closed anyio.Events,
    # no sleeps) against bare mcp==2.0.0 in an isolated venv, 2026-08-10:
    # the late response was delivered. mcp.run_stdio_async() also enters
    # the server lifespan internally now (Server.run()'s own
    # `async with self.lifespan(self)`), so no separate manual lifespan
    # entry is needed either. There is also no more banner/PyPI-update-check
    # ceremony to preserve or disable: mcp 2.0.0's MCPServer.run()/
    # run_stdio_async() do neither (verified against the installed
    # package's source, not assumed).
    anyio.run(mcp.run_stdio_async)


if __name__ == "__main__":
    main()
