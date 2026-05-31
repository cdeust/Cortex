"""Delta protocol for the Cortex layout authority.

Three input verbs (the authority RECEIVES these from the build worker):
    add_node(NodeDelta)        — a new node has been produced
    add_edge(EdgeDelta)        — a new edge has been produced
    request_subtree(domain_id) — re-emit slot assignments for one subtree

One output event (the authority PRODUCES these on the SSE stream):
    SlotAssignment             — node_id has been placed at (x, y)

Contracts here are NORMATIVE. Producers and consumers MUST honor them.
A violation is a bug. The authority's reference implementation enforces
them with assertions in debug mode and best-effort recovery in prod.

This module is contract-only. Imports stdlib only. No I/O, no logic.
A separate engineer agent will write the reference implementation in
``layout_authority.py`` integrating with the Carnot geometry module
(``layout_authority_geometry.py``), the Hamilton scheduler, and the
Lamport event log.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Protocol, runtime_checkable


# ── Allowed-value sets (NORMATIVE) ────────────────────────────────

NODE_KINDS: frozenset[str] = frozenset(
    {
        "domain",
        "skill",
        "hook",
        "command",
        "agent",
        "mcp",
        "tool_hub",
        "file",
        "discussion",
        "memory",
        "entity",
        "symbol",
    }
)

EDGE_KINDS: frozenset[str] = frozenset(
    {
        "in_domain",
        "tool_used_file",
        "defined_in",
        "calls",
        "imports",
        "member_of",
        "about_entity",
        "invoked_skill",
        "triggered_hook",
        "spawned_agent",
        "command_in_hub",
        "invoked_mcp",
        "discussion_touched_file",
        "command_touched_file",
    }
)


# ── Value types ──────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class NodeDelta:
    """An add_node event from the build worker.

    Fields:
        node_id:   stable, unique. The authority indexes by this.
        kind:      one of NODE_KINDS.
        domain_id: the id of the domain hub this node belongs to.
                   For kind == 'domain', domain_id MUST equal node_id.
        parent_id: optional. For 'symbol', this is the parent file's id.
                   For 'file', the primary tool_hub's id (if known).
                   None for everything else.
        tool_name: required iff kind == 'tool_hub' (e.g. 'Edit', 'Bash').

    Pre:
        - kind in NODE_KINDS
        - node_id non-empty
        - domain_id non-empty
        - if kind == 'domain': domain_id == node_id
        - if kind == 'tool_hub': tool_name is not None and non-empty
        - if kind == 'symbol': parent_id is not None
    Post:
        - one SlotAssignment for node_id will be emitted in bounded
          time AFTER all required parent state is present (see I3, I4).
    """

    node_id: str
    kind: str
    domain_id: str
    parent_id: Optional[str] = None
    tool_name: Optional[str] = None


@dataclass(frozen=True, slots=True)
class EdgeDelta:
    """An add_edge event from the build worker.

    Edges DO NOT change slot positions. They are forwarded to clients
    as-is and rendered as lines between already-placed nodes. The
    authority does NOT recompute layout for new edges — that's the
    whole point of the closed-form geometry.

    Pre:
        - source_id and target_id non-empty
        - kind in EDGE_KINDS
        - source_id and target_id were both previously add_node'd
          (the authority tolerates out-of-order arrival by buffering
          edges whose endpoints haven't landed yet, but the build
          worker SHOULD emit nodes before edges; see I5)
    Post:
        - the authority emits NO SlotAssignment in response to add_edge.
          (Edges are streamed via a SEPARATE event kind handled by the
          wire layer — see layout_authority_wire.py.)
    """

    source_id: str
    target_id: str
    kind: str


@dataclass(frozen=True, slots=True)
class SlotAssignment:
    """The authority's output: node_id has been placed at (x, y).

    Stable for the lifetime of the node. The authority MUST NOT re-emit
    a different (x, y) for the same node_id unless a request_subtree()
    explicitly invalidates the subtree. (request_subtree is for window
    resize and explicit user actions; not for normal streaming.)

    Fields:
        seq:       monotonic sequence number assigned by the authority.
                   Strictly increasing per authority instance. Clients
                   MUST update by seq (see I2).
        node_id:   the id this slot is for.
        x, y:      pixel coordinates in the authority's coordinate
                   system (default 1000x1000). The client scales to
                   its viewport. Always finite (see I1).
        kind:      copied from the NodeDelta — saves the client a lookup.
        domain_id: copied from the NodeDelta — used by the client to
                   color/group on arrival.
    """

    seq: int
    node_id: str
    x: float
    y: float
    kind: str
    domain_id: str


# ── The authority interface ───────────────────────────────────────

# A subscriber queue is any object with a non-blocking ``put`` that
# accepts SlotAssignment | edge events. The reference implementation
# uses ``queue.SimpleQueue``. Typed as Any to avoid stdlib coupling
# in this contract module.
EventQueue = Any


@runtime_checkable
class LayoutAuthority(Protocol):
    """The contract any layout-authority implementation must satisfy.

    Threading model:
        - add_node, add_edge are called from the build worker thread.
        - emission (SlotAssignment) reaches subscribers via their
          EventQueue, drained by SSE handler threads.
        - request_subtree may be called from any thread.
        - subscribe / unsubscribe may be called from any thread.

    Memory model:
        - state size is O(domains × kinds) — see
          layout_authority_geometry. The authority MUST NOT hold full
          node lists or edge lists. Each input verb is amortized O(1).

    Failure modes:
        - add_node with kind not in NODE_KINDS: raises ValueError.
        - add_node violating a per-kind precondition (see NodeDelta):
          raises ValueError.
        - add_edge with kind not in EDGE_KINDS: raises ValueError.
        - add_edge whose endpoints are unknown: queued in a small
          (bounded) pending-edges buffer; flushed when the second
          endpoint arrives. See I5 for buffer-overflow behavior.
        - request_subtree on unknown domain_id: returns silently
          (idempotent on a graph that's still being built).
    """

    def add_node(self, delta: NodeDelta) -> None: ...
    def add_edge(self, delta: EdgeDelta) -> None: ...
    def request_subtree(self, domain_id: str) -> None: ...

    def subscribe(self) -> EventQueue:
        """Returns a queue-like object. Caller drains slot/edge events
        and unsubscribes when done."""
        ...

    def unsubscribe(self, q: EventQueue) -> None: ...


# ── Invariants the reference implementation must check ────────────

INVARIANTS = """
I1. SlotAssignment.x and SlotAssignment.y are finite floats; never
    NaN, never inf. Verified at emission time.

I2. SlotAssignment.seq is strictly monotonically increasing per
    authority instance. For any two SlotAssignments with the same
    node_id (which can only occur after request_subtree), the LATER
    one (higher seq) supersedes the earlier. Clients MUST update by
    seq.

I3. SlotAssignment for a 'symbol' node_id must arrive AFTER the
    SlotAssignment for its parent file. If the file is missing,
    the symbol is buffered. Symbol slot is computed from parent
    file's slot, NOT from the domain anchor directly.

I4. SlotAssignment for a 'file' node_id may arrive before its primary
    tool_hub if the build worker emits files first. The authority
    falls back to placing the file at the domain hub if no tool_hub
    is yet known; the slot is FINAL — no retroactive reseat.

I5. The pending-edges buffer has a bounded size (default 100k). When
    full, the oldest pending edges are dropped (with a counter
    incremented). The build worker MUST emit dependencies in order
    most of the time; the buffer is for transient races only.

I6. add_node, add_edge, request_subtree never block. If the internal
    work queue is full, they drop the event and increment a counter.
    The producer (build worker) is never stalled by the authority.

I7. domain_id on every NodeDelta and SlotAssignment is non-empty and
    refers to a node whose kind == 'domain'. The 'domain' node for
    a domain_id MAY arrive after its members; in that case those
    members' slots are computed against a placeholder anchor and
    are FINAL (no retroactive reseat — same rule as I4).
"""


# ── Convenience factory ───────────────────────────────────────────


def authority_from_geometry(
    width: float = 1000.0,
    height: float = 1000.0,
) -> LayoutAuthority:
    """Build the reference implementation. Wired in
    ``layout_authority.py`` — this stub forward-declares only and
    defers the import to call time to keep this module pure."""
    from mcp_server.server.layout_authority import build_authority

    return build_authority(width=width, height=height)
