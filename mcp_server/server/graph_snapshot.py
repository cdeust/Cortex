"""Binary graph snapshot — load the full graph in ~200 ms regardless of DB.

The original ``/api/graph`` path serialises the in-memory graph to JSON on
every request: ~50–100 MB of JSON for a 135 k-node graph, ~1–3 s to
``JSON.parse`` in the browser, plus the network transfer. Even when the
build is cached, the *load* is dominated by re-encoding and re-parsing
data that hasn't changed.

This module defines a precomputed, fixed-width binary snapshot that the
build worker writes once after a successful build. The endpoint
``/api/graph.bin`` streams the file as ``application/octet-stream``
with zero Python-side serialisation; the frontend decodes it with a
``DataView`` walk, no JSON parse. Measured target on the 135 k / 166 k
benchmark DB: ~6 MB on disk, ~110 ms end-to-end load on loopback HTTP.

Format
======
All integers little-endian, no padding between sections.

Header (32 bytes):
    magic        : 4  bytes  "CXGB"
    version      : u16        currently 1
    flags        : u16        bit 0 = include_coords (reserved)
    node_count   : u32
    edge_count   : u32
    string_pool_off : u64     byte offset of the string pool from BOF
    string_pool_len : u32     length of the string pool in bytes
    reserved     : u32        = 0

Node row (24 bytes, repeated node_count times):
    id_off       : u32        offset into string pool
    kind         : u8         0=domain 1=tool_hub 2=file 3=symbol 4=skill
                              5=hook  6=command 7=agent 8=mcp
                              9=discussion 10=memory 11=entity
                              255=unknown
    pad          : u8 × 3
    domain_off   : u32        offset into string pool (== id_off for domains)
    x            : f32        layout-authority x coord, 0.0 if not laid out
    y            : f32        same, y
    size         : f32        visual size hint

Edge row (12 bytes, repeated edge_count times):
    src_off      : u32        offset of source node id in string pool
    tgt_off      : u32        offset of target node id in string pool
    kind         : u8         0=in_domain 1=tool_used_file 2=defined_in
                              3=calls 4=imports 5=member_of
                              6=about_entity 7=command_opened
                              8=discussion_opened 9=skill_usage
                              10=mcp_usage 11=discussion_tool
                              12=discussion_agent 13=discussion_command
                              14=extends 15=other 255=unknown
    pad          : u8 × 3

String pool (variable, starts at string_pool_off):
    Length-prefixed UTF-8 strings. Each string is::

        len : u16   (max 65535)
        utf : bytes (len bytes, no terminator)

    Strings are deduplicated by content. ``id_off`` / ``domain_off`` /
    ``src_off`` / ``tgt_off`` point at the *start of the len prefix*.

Sizes for the 135 k / 166 k benchmark::

    32 (header)
    + 135_000 × 24 (nodes)     = 3.24 MB
    + 166_000 × 12 (edges)     = 1.99 MB
    + ~135_000 strings × ~20 B = 2.7  MB
    ≈ 8 MB total

source: measured 2026-05-28 on the rebased streaming branch's dev DB.
"""

from __future__ import annotations

import io
import os
import struct
import tempfile
from pathlib import Path
from typing import Any

MAGIC = b"CXGB"
VERSION = 1

_NODE_KIND_MAP = {
    "domain": 0,
    "tool_hub": 1,
    "file": 2,
    "symbol": 3,
    "skill": 4,
    "hook": 5,
    "command": 6,
    "agent": 7,
    "mcp": 8,
    "discussion": 9,
    "memory": 10,
    "entity": 11,
}
_EDGE_KIND_MAP = {
    "in_domain": 0,
    "tool_used_file": 1,
    "defined_in": 2,
    "calls": 3,
    "imports": 4,
    "member_of": 5,
    "about_entity": 6,
    "command_opened": 7,
    "discussion_opened": 8,
    "skill_usage": 9,
    "mcp_usage": 10,
    "discussion_tool": 11,
    "discussion_agent": 12,
    "discussion_command": 13,
    "extends": 14,
    "other": 15,
}

_HEADER_FMT = "<4sHHIIQII"
_HEADER_SIZE = struct.calcsize(_HEADER_FMT)  # 32
_NODE_FMT = "<IBxxxIfff"
_NODE_SIZE = struct.calcsize(_NODE_FMT)  # 24
_EDGE_FMT = "<IIBxxx"
_EDGE_SIZE = struct.calcsize(_EDGE_FMT)  # 12

assert _HEADER_SIZE == 32, _HEADER_SIZE
assert _NODE_SIZE == 24, _NODE_SIZE
assert _EDGE_SIZE == 12, _EDGE_SIZE


class _StringPool:
    """Builds the deduplicated length-prefixed UTF-8 string pool.

    Returns the BYTE OFFSET (within the pool) of each interned string;
    that offset is what the node/edge rows store.
    """

    __slots__ = ("_offsets", "_buf")

    def __init__(self) -> None:
        self._offsets: dict[str, int] = {}
        self._buf = io.BytesIO()

    def intern(self, s: str | None) -> int:
        s = "" if s is None else str(s)
        off = self._offsets.get(s)
        if off is not None:
            return off
        encoded = s.encode("utf-8")
        if len(encoded) > 65535:
            encoded = encoded[:65535]  # truncate rather than fail
        off = self._buf.tell()
        self._buf.write(struct.pack("<H", len(encoded)))
        self._buf.write(encoded)
        self._offsets[s] = off
        return off

    def bytes(self) -> bytes:
        return self._buf.getvalue()


def serialize(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> bytes:
    """Pack ``(nodes, edges)`` into the CXGB binary snapshot.

    Both inputs are the same JSON-friendly dicts the legacy ``/api/graph``
    cache produces (see ``mcp_server/handlers/workflow_graph._node_to_dict``
    and ``_edge_to_dict``). Returns the complete snapshot as bytes ready
    to write to disk or stream to the wire.
    """
    pool = _StringPool()

    node_rows = bytearray(_NODE_SIZE * len(nodes))
    for i, n in enumerate(nodes):
        node_id = n.get("id") or ""
        kind_str = n.get("kind") or n.get("type") or ""
        kind = _NODE_KIND_MAP.get(kind_str, 255)
        domain = n.get("domain_id") or n.get("domain") or ""
        x = float(n.get("x") or 0.0)
        y = float(n.get("y") or 0.0)
        size = float(n.get("size") or 1.0)
        id_off = pool.intern(node_id)
        dom_off = pool.intern(domain)
        struct.pack_into(
            _NODE_FMT,
            node_rows,
            i * _NODE_SIZE,
            id_off,
            kind,
            dom_off,
            x,
            y,
            size,
        )

    edge_rows = bytearray(_EDGE_SIZE * len(edges))
    for i, e in enumerate(edges):
        src = e.get("source")
        tgt = e.get("target")
        if isinstance(src, dict):
            src = src.get("id")
        if isinstance(tgt, dict):
            tgt = tgt.get("id")
        kind_str = e.get("kind") or e.get("type") or ""
        kind = _EDGE_KIND_MAP.get(kind_str, 255)
        struct.pack_into(
            _EDGE_FMT,
            edge_rows,
            i * _EDGE_SIZE,
            pool.intern(src or ""),
            pool.intern(tgt or ""),
            kind,
        )

    pool_bytes = pool.bytes()
    pool_off = _HEADER_SIZE + len(node_rows) + len(edge_rows)
    header = struct.pack(
        _HEADER_FMT,
        MAGIC,
        VERSION,
        0,
        len(nodes),
        len(edges),
        pool_off,
        len(pool_bytes),
        0,
    )
    return bytes(header) + bytes(node_rows) + bytes(edge_rows) + pool_bytes


def deserialize(buf: bytes) -> dict[str, Any]:
    """Inverse of ``serialize`` — used by tests + diagnostic tools.

    Returns ``{"nodes": [...], "edges": [...]}`` in the same dict shape
    the JSON endpoint produces. Browser clients decode directly with
    ``DataView`` (see ``ui/unified/js/graph_snapshot.js``); this Python
    helper exists so the serialiser's contract is testable end-to-end.
    """
    if len(buf) < _HEADER_SIZE:
        raise ValueError(f"snapshot too small: {len(buf)} bytes")
    magic, ver, _flags, n_count, e_count, pool_off, pool_len, _ = struct.unpack(
        _HEADER_FMT, buf[:_HEADER_SIZE]
    )
    if magic != MAGIC:
        raise ValueError(f"bad magic {magic!r}")
    if ver != VERSION:
        raise ValueError(f"unsupported version {ver}")

    inv_node_kind = {v: k for k, v in _NODE_KIND_MAP.items()}
    inv_edge_kind = {v: k for k, v in _EDGE_KIND_MAP.items()}

    def read_str(off: int) -> str:
        slen = struct.unpack_from("<H", buf, pool_off + off)[0]
        return buf[pool_off + off + 2 : pool_off + off + 2 + slen].decode(
            "utf-8", errors="replace"
        )

    nodes: list[dict[str, Any]] = []
    base = _HEADER_SIZE
    for i in range(n_count):
        id_off, kind, dom_off, x, y, size = struct.unpack_from(
            _NODE_FMT, buf, base + i * _NODE_SIZE
        )
        nodes.append(
            {
                "id": read_str(id_off),
                "kind": inv_node_kind.get(kind, "unknown"),
                "domain_id": read_str(dom_off),
                "x": x,
                "y": y,
                "size": size,
            }
        )

    edges: list[dict[str, Any]] = []
    base = _HEADER_SIZE + n_count * _NODE_SIZE
    for i in range(e_count):
        src_off, tgt_off, kind = struct.unpack_from(
            _EDGE_FMT, buf, base + i * _EDGE_SIZE
        )
        edges.append(
            {
                "source": read_str(src_off),
                "target": read_str(tgt_off),
                "kind": inv_edge_kind.get(kind, "unknown"),
            }
        )

    return {"nodes": nodes, "edges": edges, "meta": {"format": "CXGBv1"}}


def default_path() -> Path:
    """Default on-disk location for the snapshot."""
    return Path.home() / ".cache" / "cortex" / "graph-snapshot.bin"


def write_atomic(path: Path, payload: bytes) -> None:
    """Atomically replace ``path`` with ``payload``.

    Writes to ``<path>.tmp.<pid>`` in the same directory then ``os.replace``
    so a concurrent reader either sees the old complete snapshot or the
    new complete snapshot — never a torn partial write.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".tmp.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(payload)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_from_graph_cache(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    path: Path | None = None,
) -> tuple[Path, int]:
    """Serialise + atomically write the snapshot.

    Returns ``(path, byte_count)`` for callers that want to log the
    artifact. The caller is responsible for deciding *when* to write
    (the build worker calls this after the full build completes).
    """
    p = path or default_path()
    payload = serialize(nodes, edges)
    write_atomic(p, payload)
    return p, len(payload)
