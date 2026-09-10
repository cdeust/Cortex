"""AP is a Rust MCP server that indexes codebases into a property graph
(tree-sitter → LadybugDB → Louvain → BM25 + TF-IDF + RRF) and exposes
23 tools. Cortex consumes a subset of those tools — indexing, graph
queries, symbol lookup, search — to add AST-level depth to its
workflow graph.

Infrastructure layer only. No core imports.

source: ADR-0501"""

from __future__ import annotations

import asyncio
import logging
import os
import sys

from mcp_server.infrastructure.upstream_identity import (
    ALLOWED_UPSTREAM_COMMANDS,
    PLUGIN_KEY_BINARIES,
)
from typing import Any

from mcp_server.errors import McpConnectionError
from mcp_server.infrastructure.mcp_call_timeout import interactive_call_timeout_s
from mcp_server.infrastructure.mcp_client import MCPClient
from mcp_server.observability import silent_failure
from mcp_server.infrastructure.memory_config import get_memory_settings
from pathlib import Path
import json

logger = logging.getLogger(__name__)

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

    source: ADR-0501"""
    try:
        return bool(get_memory_settings().AP_ENABLED)
    except Exception as exc:  # noqa: BLE001 — config unavailable (test import-order edge case): on-by-default; observable via silent_failure
        silent_failure.note("ap_bridge.settings_read", exc)
        # source: ADR-0501
        return True


def resolve_graph_path() -> str | None:
    """Return a LadybugDB graph path (single-graph callers).

    source: ADR-0501"""
    raw = (os.environ.get("CORTEX_AP_GRAPH_PATH") or "").strip()
    if raw:
        return raw

    default = Path.home() / ".cortex" / "ap_graph" / "graph"
    if default.exists():
        return str(default)
    paths = resolve_graph_paths()
    return paths[0] if paths else None


def resolve_graph_paths() -> list[str]:
    """Return every LadybugDB graph the visualization should query.

        Each candidate must exist (file or directory — AP's LadybugDB is a
        single ``graph`` file with a ``graph.wal`` sibling, NOT a directory;
        earlier filtering on ``is_dir`` silently dropped every valid graph).

    source: ADR-0501"""
    paths: list[str] = []
    seen: set[str] = set()

    def _add(p) -> None:
        s = str(p)
        if s in seen or not p.exists():
            return
        paths.append(s)
        seen.add(s)

    raw = (os.environ.get("CORTEX_AP_GRAPH_PATH") or "").strip()
    if raw:
        _add(Path(raw))

    legacy = Path.home() / ".cortex" / "ap_graph" / "graph"
    _add(legacy)

    for roster in (
        Path.home() / ".cortex" / "ap_graphs",
        Path.home() / ".cache" / "cortex" / "code-graphs",
    ):
        if roster.is_dir():
            for project_dir in sorted(roster.iterdir()):
                _add(project_dir / "graph")
    return paths


def _resolve_command() -> dict | None:
    """Resolve the MCP-client config for AP.

        Returns None when no AP install can be discovered; callers treat
        that as graceful degradation (ingest_codebase fails with the
        standard McpConnectionError).

    source: ADR-0501"""
    raw = os.environ.get("CORTEX_AP_COMMAND")
    if raw:
        try:
            cfg = json.loads(raw)
        except ValueError:
            return None
        if isinstance(cfg, dict) and "command" in cfg:
            return cfg

    home = Path.home()
    # source: ADR-0501
    bin_path = home / ".claude/methodology/bin/mcp-server"
    if bin_path.is_file() and os.access(bin_path, os.X_OK):
        # source: ADR-0501
        return {"command": str(bin_path), "args": []}
    # source: ADR-0501

    installed = home / ".claude/plugins/installed_plugins.json"
    try:
        data = json.loads(installed.read_text(encoding="utf-8"))
        plugins = data.get("plugins", {}) if isinstance(data, dict) else {}
        # source: ADR-0501
        for plugin_key, binary_name in PLUGIN_KEY_BINARIES:
            entries = plugins.get(plugin_key)
            if not isinstance(entries, list) or not entries:
                continue
            install_path = entries[0].get("installPath")
            if not install_path:
                continue
            binary = Path(install_path) / "target" / "release" / binary_name
            if binary.is_file() and os.access(binary, os.X_OK):
                return {"command": str(binary), "args": []}
    except (OSError, ValueError, KeyError, IndexError, TypeError, AttributeError):
        pass
    return None


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
        # source: ADR-0501
        if self._connected and self._client is not None and self._client.connected:
            return True
        async with self._lock:
            if self._connected and self._client is not None and self._client.connected:
                return True
            # source: ADR-0501
            if self._client is not None and not self._client.connected:
                self._client = None
            self._connected = False
            cfg = self._config or _resolve_command()
            if cfg is None:
                self._unavailable_reason = "no_command_resolved"
                return False
            try:
                # source: ADR-0501
                cfg = {**cfg, "callTimeoutMs": 0}
                self._client = MCPClient(cfg)
                # source: ADR-0501
                self._client._extra_allowed_commands = {
                    "node",
                    *ALLOWED_UPSTREAM_COMMANDS,
                }
                await self._client.connect()
                self._connected = True
                self._unavailable_reason = None  # clear any stale poison
                return True
            except (McpConnectionError, Exception) as exc:  # noqa: BLE001 — failure is reported to stderr; execution degrades, never crashes
                # source: ADR-0501
                self._connected = False
                self._client = None
                self._unavailable_reason = f"{type(exc).__name__}: {exc}"
                print(
                    f"[cortex] AP bridge disabled: {self._unavailable_reason}",
                    file=sys.stderr,
                )
                return False

    def _degrade(self, reason: str, note: str) -> None:
        """Record why the last AP call failed and emit the stderr note.

        source: ADR-0501"""
        self._unavailable_reason = reason
        print(note, file=sys.stderr)

    async def call(
        self, tool: str, args: dict | None = None, *, timeout_s: float | None = None
    ) -> Any:
        """Call an AP tool. Returns ``None`` if AP is unavailable.

        source: ADR-0501"""
        if tool not in _AP_TOOLS:
            raise ValueError(f"AP tool not in allowlist: {tool!r}")
        self._unavailable_reason = None  # source: ADR-0501
        if not await self.connect():
            return None
        if self._client is None:  # source: ADR-0501
            return None
        try:
            coro = self._client.call(tool, args or {})
            if timeout_s is not None:
                return await asyncio.wait_for(coro, timeout=timeout_s)
            return await coro
        except asyncio.TimeoutError:  # source: ADR-0501
            self._degrade(
                f"TimeoutError: AP call {tool} exceeded {timeout_s:.0f}s",
                f"[cortex] AP call {tool} timed out after {timeout_s:.0f}s "
                f"(interactive ceiling); degrading to Cortex-only.",
            )
            return None
        except Exception as exc:  # noqa: BLE001 — failure is reported to stderr; execution degrades, never crashes
            self._degrade(
                f"{type(exc).__name__}: {exc}",
                f"[cortex] AP call {tool} failed: {exc}",
            )
            return None

    # source: ADR-0501
    async def health_check(self) -> Any:
        return await self.call(
            "health_check", {}, timeout_s=interactive_call_timeout_s()
        )

    async def index_codebase(
        self,
        path: str,
        *,
        output_dir: str,
        language: str = "auto",
    ) -> Any:
        """Index ``path`` into a LadybugDB graph at ``output_dir``.

        source: ADR-0501"""
        return await self.call(
            "index_codebase",
            {"path": path, "output_dir": output_dir, "language": language},
        )

    async def query_graph(self, graph_path: str, query: str) -> Any:
        """Execute a Cypher ``query`` against the graph at ``graph_path``.

        Left UNBOUNDED: query_graph drives the AST symbol/edge build loop
        (iter_symbols / iter_edges, ~21 label + ~89 rel-table queries per
        graph), which is part of the ingestion path where a single query
        over a large graph may legitimately run long. Only the terminal
        interactive lookups (get_symbol / get_context / search_codebase /
        …) carry the interactive ceiling.
        """
        return await self.call(
            "query_graph",
            {"graph_path": graph_path, "query": query},
        )

    async def get_symbol(self, graph_path: str, qualified_name: str) -> Any:
        """Look up a symbol by its ``file::name`` qualified name."""
        return await self.call(
            "get_symbol",
            {"graph_path": graph_path, "qualified_name": qualified_name},
            timeout_s=interactive_call_timeout_s(),
        )

    async def get_context(self, graph_path: str, qualified_name: str) -> Any:
        """360° symbol view: calls/called_by, imports/imported_by,
                implements/implemented_by, uses/used_by, community, processes.

        source: ADR-0501"""
        return await self.call(
            "get_context",
            {"graph_path": graph_path, "qualified_name": qualified_name},
            timeout_s=interactive_call_timeout_s(),
        )

    async def get_processes(self, graph_path: str) -> Any:
        """All detected execution flows (causal chains) from entry points.

        source: ADR-0501"""
        return await self.call(
            "get_processes",
            {"graph_path": graph_path},
            timeout_s=interactive_call_timeout_s(),
        )

    async def resolve_graph(self, graph_path: str) -> Any:
        """Stage 3b — resolve cross-file edges (Imports/Calls/Implements/
        Extends/Uses) by matching string refs to concrete target nodes."""
        return await self.call("resolve_graph", {"graph_path": graph_path})

    async def cluster_graph(
        self, graph_path: str, *, resolution_param: float = 1.0
    ) -> Any:
        """Stage 3c — community detection + process tracing. Must run before
        get_impact / get_processes return non-empty results."""
        return await self.call(
            "cluster_graph",
            {"graph_path": graph_path, "resolution_param": resolution_param},
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
            timeout_s=interactive_call_timeout_s(),
        )

    async def detect_changes(
        self,
        graph_path: str,
        *,
        codebase_path: str | None = None,
        base_ref: str = "HEAD~1",
        head_ref: str = "HEAD",
        diff_text: str | None = None,
    ) -> Any:
        """Git-diff impact (versioning): map changed lines → affected
                symbols/communities/processes + a heuristic risk score.

        source: ADR-0501"""
        args: dict = {"graph_path": graph_path}
        if diff_text is not None:
            args["diff_text"] = diff_text
        else:
            args["base_ref"] = base_ref
            args["head_ref"] = head_ref
            if codebase_path:
                args["codebase_path"] = codebase_path
        return await self.call("detect_changes", args)

    async def get_impact(self, graph_path: str, qualified_name: str) -> Any:
        """Blast radius for a symbol: communities + processes affected.

        AP v0.0.9 keys this by ``qualified_name``, not ``symbol_id``.
        """
        return await self.call(
            "get_impact",
            {"graph_path": graph_path, "qualified_name": qualified_name},
            timeout_s=interactive_call_timeout_s(),
        )

    async def analyze_codebase(
        self,
        path: str,
        *,
        output_dir: str,
        language: str = "auto",
    ) -> Any:
        """All-in-one: runs index_codebase + resolve_graph + cluster_graph.

        source: ADR-0501"""
        return await self.call(
            "analyze_codebase",
            {"path": path, "output_dir": output_dir, "language": language},
        )

    async def close(self) -> None:
        if self._client is not None:
            try:
                # source: ADR-0501
                self._client.close()
            except Exception as exc:  # noqa: BLE001 — teardown continues past a failed close
                logger.debug("AP client close failed during teardown: %s", exc)
            self._client = None
        self._connected = False


__all__ = ["APBridge", "is_enabled"]
