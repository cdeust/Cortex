"""Bridge to the ``automatised-pipeline`` sibling MCP server (ADR-0046).

AP is a Rust MCP server that indexes codebases into a property graph
(tree-sitter → LadybugDB → Louvain → BM25 + TF-IDF + RRF) and exposes
23 tools. Cortex consumes a subset of those tools — indexing, graph
queries, symbol lookup, search — to add AST-level depth to its
workflow graph.

Enabled by default (``MemorySettings.AP_ENABLED = True``) so the L6
symbol ring has depth out of the box. Users cut token / subprocess
cost by setting ``CORTEX_MEMORY_AP_ENABLED=0`` in their MCP config.
When off, no connection is attempted, every call returns an empty
result, and the workflow graph falls back to the native in-process
AST source.

Infrastructure layer only. No core imports.
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import Any

from mcp_server.errors import McpConnectionError
from mcp_server.infrastructure.mcp_client import MCPClient

_AP_TOOLS = frozenset(
    {
        "health_check",
        "index_codebase",
        "query_graph",
        "resolve_graph",
        "cluster_graph",
        "analyze_codebase",  # all-in-one: index + resolve + cluster
        "search_codebase",
        "get_context",
        "get_symbol",
        "get_impact",
        "detect_changes",
    }
)


def is_enabled() -> bool:
    """Return True when AP enrichment is active.

    Single source of truth: ``MemorySettings.AP_ENABLED`` (reads
    ``CORTEX_MEMORY_AP_ENABLED`` via pydantic-settings env prefix).
    Default is ``True`` — the L6 symbol ring has depth out of the box.
    Users who want to cut token / subprocess cost set
    ``CORTEX_MEMORY_AP_ENABLED=0`` in their MCP server env block.

    AP absence still degrades gracefully: ``APBridge.connect()`` returns
    False silently and every tool call short-circuits to []; the native
    in-process AST source fills the L6 ring.
    """
    try:
        from mcp_server.infrastructure.memory_config import get_memory_settings

        return bool(get_memory_settings().AP_ENABLED)
    except Exception:
        # Config system unavailable (e.g. test import-order edge case):
        # fall back to the on-by-default contract.
        return True


def resolve_graph_path() -> str | None:
    """Return a LadybugDB graph path (single-graph callers).

    Preference order:
      1. ``CORTEX_AP_GRAPH_PATH`` env var (explicit caller override).
      2. The conventional legacy location ``$HOME/.cortex/ap_graph/graph``.
      3. The first graph in the multi-project roster (``resolve_graph_paths``).
    """
    raw = (os.environ.get("CORTEX_AP_GRAPH_PATH") or "").strip()
    if raw:
        return raw
    from pathlib import Path

    default = Path.home() / ".cortex" / "ap_graph" / "graph"
    if default.exists():
        return str(default)
    paths = resolve_graph_paths()
    return paths[0] if paths else None


def resolve_graph_paths() -> list[str]:
    """Return every LadybugDB graph the visualization should query.

    Multi-project layout: Cortex keeps one graph per project under
    ``$HOME/.cortex/ap_graphs/<project-name>/graph``. Each directory
    holds an independent AP index (one for Cortex, one for
    dcp-wealth-android, one for automatised-pipeline, …). The
    workflow graph loader sweeps every path so the visualization
    shows AST symbols from every project at once — no limitation,
    no hard-coded selection.
    """
    paths: list[str] = []
    raw = (os.environ.get("CORTEX_AP_GRAPH_PATH") or "").strip()
    if raw:
        # Honour an explicit single-graph override if the user set it.
        paths.append(raw)
    from pathlib import Path

    legacy = Path.home() / ".cortex" / "ap_graph" / "graph"
    if legacy.exists() and str(legacy) not in paths:
        paths.append(str(legacy))
    roster = Path.home() / ".cortex" / "ap_graphs"
    if roster.is_dir():
        for project_dir in sorted(roster.iterdir()):
            g = project_dir / "graph"
            if g.exists() and str(g) not in paths:
                paths.append(str(g))
    return paths


def _resolve_command() -> dict | None:
    """Resolve the MCP-client config for AP.

    Priority:
      1. ``CORTEX_AP_COMMAND`` env var — full shell-free invocation
         spec (JSON: ``{"command": "...", "args": [...]}``).
      2. Plugin-cache probe — ``automatised-pipeline`` installed as
         a sibling plugin exposes its MCP entrypoint via
         ``~/.claude/plugins/cache/<mp>/automatised-pipeline/*``.
      3. ``uvx`` fallback for the pip-published crate.
    """
    raw = os.environ.get("CORTEX_AP_COMMAND")
    if raw:
        import json

        try:
            cfg = json.loads(raw)
        except ValueError:
            return None
        if isinstance(cfg, dict) and "command" in cfg:
            return cfg
    # Plugin-cache probe.
    from pathlib import Path

    home = Path.home()
    for root in (home / ".claude/plugins/cache").glob("*/automatised-pipeline/*/bin/*"):
        if root.is_file() and os.access(root, os.X_OK):
            return {"command": "node", "args": [str(root)]}
    # uvx fallback.
    return {
        "command": "uvx",
        "args": ["--from", "automatised-pipeline", "automatised-pipeline"],
    }


class APBridge:
    """Thin wrapper around ``MCPClient`` scoped to AP's tool namespace.

    Lazy-connects on first call. Safe to construct unconditionally —
    ``connect()`` bails out when the feature flag is off.
    """

    def __init__(self, config: dict | None = None) -> None:
        self._config = config
        self._client: MCPClient | None = None
        self._lock = asyncio.Lock()
        self._connected = False
        self._unavailable_reason: str | None = None

    @property
    def available(self) -> bool:
        """True iff the flag is on and no prior connect attempt failed."""
        return is_enabled() and self._unavailable_reason is None

    @property
    def unavailable_reason(self) -> str | None:
        return self._unavailable_reason

    async def connect(self) -> bool:
        """Connect on demand. Returns False if the flag is off or the
        server can't be reached; the caller treats that as graceful
        degradation, not an error."""
        if not is_enabled():
            self._unavailable_reason = "disabled"
            return False
        if self._connected:
            return True
        async with self._lock:
            if self._connected:
                return True
            cfg = self._config or _resolve_command()
            if cfg is None:
                self._unavailable_reason = "no_command_resolved"
                return False
            try:
                # Indexing a large mobile codebase (tens of thousands of
                # files) can take longer than the default 120 s call
                # timeout; raise to 10 minutes so ``index_codebase`` and
                # ``analyze_codebase`` don't get cut short.
                cfg = {**cfg, "callTimeoutMs": 600000}
                self._client = MCPClient(cfg)
                # AP's binary is not in the default allowlist.
                # ``ai-architect-mcp`` is the crate name in
                # automatised-pipeline; the others are fallbacks for
                # the plugin-cache / uvx resolution paths.
                self._client._extra_allowed_commands = {
                    "node",
                    "uvx",
                    "automatised-pipeline",
                    "ai-architect-mcp",
                }
                await self._client.connect()
                self._connected = True
                return True
            except (McpConnectionError, Exception) as exc:
                self._unavailable_reason = f"{type(exc).__name__}: {exc}"
                print(
                    f"[cortex] AP bridge disabled: {self._unavailable_reason}",
                    file=sys.stderr,
                )
                return False

    async def call(self, tool: str, args: dict | None = None) -> Any:
        """Call an AP tool. Returns ``None`` if AP is unavailable."""
        if tool not in _AP_TOOLS:
            raise ValueError(f"AP tool not in allowlist: {tool!r}")
        if not await self.connect():
            return None
        try:
            return await self._client.call(tool, args or {})
        except Exception as exc:
            self._unavailable_reason = f"{type(exc).__name__}: {exc}"
            print(
                f"[cortex] AP call {tool} failed: {exc}",
                file=sys.stderr,
            )
            return None

    # ── Convenience wrappers matching AP's MCP schema (src/tool_schemas.rs).
    # All Stage-3a tools are scoped to a ``graph_path`` returned by
    # index_codebase; callers pass it through or rely on the cached one.
    async def health_check(self) -> Any:
        return await self.call("health_check", {})

    async def index_codebase(
        self,
        path: str,
        *,
        output_dir: str,
        language: str = "auto",
    ) -> Any:
        """Index ``path`` into a LadybugDB graph at ``output_dir``.

        AP requires both ``path`` (source root) and ``output_dir``
        (where ``graph/`` lives). Returns a dict including
        ``graph_path``; subsequent calls must pass that path.
        """
        return await self.call(
            "index_codebase",
            {"path": path, "output_dir": output_dir, "language": language},
        )

    async def query_graph(self, graph_path: str, query: str) -> Any:
        """Execute a Cypher ``query`` against the graph at ``graph_path``."""
        return await self.call(
            "query_graph",
            {"graph_path": graph_path, "query": query},
        )

    async def get_symbol(self, graph_path: str, qualified_name: str) -> Any:
        """Look up a symbol by its ``file::name`` qualified name."""
        return await self.call(
            "get_symbol",
            {"graph_path": graph_path, "qualified_name": qualified_name},
        )

    async def get_context(self, graph_path: str, symbol_id: str) -> Any:
        return await self.call(
            "get_context",
            {"graph_path": graph_path, "symbol_id": symbol_id},
        )

    async def search_codebase(
        self,
        graph_path: str,
        query: str,
        *,
        limit: int = 20,
    ) -> Any:
        return await self.call(
            "search_codebase",
            {"graph_path": graph_path, "query": query, "limit": limit},
        )

    async def detect_changes(
        self,
        graph_path: str,
        *,
        base: str = "HEAD~1",
        head: str = "HEAD",
    ) -> Any:
        return await self.call(
            "detect_changes",
            {"graph_path": graph_path, "base": base, "head": head},
        )

    async def get_impact(self, graph_path: str, symbol_id: str) -> Any:
        return await self.call(
            "get_impact",
            {"graph_path": graph_path, "symbol_id": symbol_id},
        )

    async def analyze_codebase(
        self,
        path: str,
        *,
        output_dir: str,
        language: str = "auto",
    ) -> Any:
        """All-in-one: runs index_codebase + resolve_graph + cluster_graph.

        search_codebase (Stage 3d) requires all three to have run; use
        this when you want Phase-3 unified search against a fresh index.
        """
        return await self.call(
            "analyze_codebase",
            {"path": path, "output_dir": output_dir, "language": language},
        )

    async def close(self) -> None:
        if self._client is not None:
            try:
                await self._client.close()
            except Exception:
                pass
            self._client = None
        self._connected = False


__all__ = ["APBridge", "is_enabled"]
