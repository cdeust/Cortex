#!/usr/bin/env python3
"""One-shot: fetch the full graph from the running server and write the
CXGB binary snapshot to disk. Run this once; the Rust app reads it directly.

Usage:
  uv run python3 scripts/dump_snapshot.py
"""
import sys
import urllib.request
import json
from pathlib import Path

SERVER = "http://127.0.0.1:3458"

print("[dump] Fetching full graph from server…", flush=True)
try:
    with urllib.request.urlopen(f"{SERVER}/api/graph", timeout=120) as r:
        data = json.load(r)
except Exception as e:
    print(f"[dump] Failed to fetch graph: {e}", file=sys.stderr)
    print(f"[dump] Make sure the server is running: CORTEX_IDLE_TIMEOUT=7200 uv run python3 mcp_server/server/http_standalone.py --type unified --port 3458", file=sys.stderr)
    sys.exit(1)

nodes = data.get("nodes", [])
edges = data.get("edges", data.get("links", []))

print(f"[dump] Got {len(nodes):,} nodes, {len(edges):,} edges", flush=True)
print("[dump] Writing CXGB snapshot…", flush=True)

# Add this project to sys.path so we can use the existing snapshot writer
sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp_server.server.graph_snapshot import write_from_graph_cache

snap_path, snap_bytes = write_from_graph_cache(nodes, edges)
print(f"[dump] Written: {snap_bytes:,} bytes → {snap_path}", flush=True)
print(f"[dump] Done. The Cortex native app will read this file directly.", flush=True)
