"""Reproducible benchmark harness for the Cortex layout authority.

Profile-before-optimize (Knuth 1974, Computing Surveys 6(4)): MEASURES
where time is spent — does not speculate. Three component micro-benches
(geometry, scheduler, log) + one integration bench; each reports
ns/op and ops/sec. Run::
    python3 -m mcp_server.server.bench_layout_authority [--n N]
Default N=1e6 nodes, 4*N edges; kind mix: 10 domains / 70 tool_hubs /
30k files / 250k symbols / 250k memories / 100k entities / 50k
discussions / pad with skill/hook/command/agent/mcp.
"""

from __future__ import annotations

import argparse
import math
import sys
import time
from dataclasses import dataclass
from typing import Callable

from mcp_server.server.layout_authority_geometry import (
    base_radius,
    compute_slot,
    domain_anchor,
    outward_angle,
    tool_hub_angle,
)
from mcp_server.server.layout_authority_log import (
    emit,
    replay_since,
    reset as log_reset,
)
from mcp_server.server.layout_authority_protocol import EdgeDelta
from mcp_server.server.layout_authority_scheduler import (
    PriorityScheduler,
    priority_for_edge,
    priority_for_node,
)
from mcp_server.server.layout_authority_wire import format_edge, format_slot


# ── Workload synthesis ──────────────────────────────────────────────────


@dataclass(slots=True)
class _WireSlot:  # duck-types what format_slot reads (.node_id/.x/.y/.kind/.domain_id)
    node_id: str
    x: float
    y: float
    kind: str
    domain_id: str  # noqa: E702


@dataclass(frozen=True, slots=True)
class WorkloadSpec:
    n_total: int
    n_domains: int = 10
    n_tool_hubs: int = 70
    n_files: int = 30_000
    n_symbols: int = 250_000
    n_memories: int = 250_000
    n_entities: int = 100_000
    n_discussions: int = 50_000

    def padding(self) -> int:
        used = (
            self.n_domains
            + self.n_tool_hubs
            + self.n_files
            + self.n_symbols
            + self.n_memories
            + self.n_entities
            + self.n_discussions
        )
        return max(self.n_total - used, 0)


def synthesize_kinds(spec: WorkloadSpec) -> list[str]:
    """Kind string per node, in production arrival order."""
    s = spec
    parts = (
        ("domain", s.n_domains),
        ("tool_hub", s.n_tool_hubs),
        ("file", s.n_files),
        ("symbol", s.n_symbols),
        ("memory", s.n_memories),
        ("entity", s.n_entities),
        ("discussion", s.n_discussions),
    )
    out: list[str] = [k for k, c in parts for _ in range(c)]
    fillers = ("skill", "hook", "command", "agent", "mcp")
    out.extend(fillers[i % len(fillers)] for i in range(s.padding()))
    return out[: s.n_total]


def precompute_anchors(nd: int, w: float = 1000.0, h: float = 1000.0):
    cx, cy, base_r = w / 2.0, h / 2.0, base_radius(w, h, nd)
    anchors = [domain_anchor(i, nd, cx, cy, base_r) for i in range(nd)]
    return anchors, [outward_angle(a, cx, cy) for a in anchors], base_r, cx, cy


def _measure(label: str, n: int, fn: Callable[[], None]) -> dict:
    t0 = time.perf_counter_ns()
    fn()
    el = time.perf_counter_ns() - t0
    return {
        "label": label,
        "n": n,
        "elapsed_ns": el,
        "ns_per_op": el / n if n else float("inf"),
        "ops_per_sec": (n / (el / 1e9)) if el else float("inf"),
    }


# ── Bench 1: geometry slot computation ──────────────────────────────────


def bench_geometry(spec: WorkloadSpec) -> dict:
    kinds = synthesize_kinds(spec)
    anchors, outwards, base_r, cx, cy = precompute_anchors(spec.n_domains)
    bucket: dict[tuple[int, str], int] = {}
    file_slots: dict[int, tuple[float, float]] = {}
    tools = ("Edit", "Write", "Read", "Grep", "Glob", "Bash", "Task")
    nd, nt = spec.n_domains, spec.n_total
    files_per = max(spec.n_files // nd, 1)
    syms_per = max(spec.n_symbols // max(spec.n_files, 1), 1)
    other_per = max(nt // nd, 1)

    def run() -> None:
        for i, kind in enumerate(kinds):
            d = i % nd
            anchor, outward = anchors[d], outwards[d]
            idx = bucket.get((d, kind), 0)
            bucket[(d, kind)] = idx + 1
            tool = tools[idx % len(tools)]
            if kind == "domain":
                ctx = {
                    "index": d,
                    "total_domains": nd,
                    "cx": cx,
                    "cy": cy,
                    "base_r": base_r,
                }
            elif kind == "tool_hub":
                ctx = {"anchor": anchor, "outward": outward, "tool_name": tool}
            elif kind == "file":
                ctx = {
                    "anchor": anchor,
                    "idx": idx,
                    "total": files_per,
                    "hub_angle": tool_hub_angle(outward, tool),
                }
            elif kind == "symbol":
                ctx = {
                    "file_slot": file_slots.get(d, anchor),
                    "idx": idx,
                    "total": syms_per,
                }
            else:
                ctx = {
                    "anchor": anchor,
                    "outward": outward,
                    "idx": idx,
                    "total": other_per,
                }
            slot = compute_slot(kind, ctx)
            if kind == "file":
                file_slots[d] = slot
            if not math.isfinite(slot[0]):  # block DCE
                raise AssertionError("non-finite slot")

    return _measure("geometry.compute_slot", nt, run)


# ── Bench 2: scheduler submit + pop round-trips ─────────────────────────


def bench_scheduler(spec: WorkloadSpec) -> dict:
    kinds = synthesize_kinds(spec)
    n_edges = spec.n_total * 4
    sched = PriorityScheduler()

    def run() -> None:
        for i, kind in enumerate(kinds):
            sched.submit(priority_for_node(kind), (i, kind))
        ep = priority_for_edge()
        for i in range(n_edges):
            sched.submit(ep, i)
        total = spec.n_total + n_edges
        for _ in range(total):
            if sched.pop(timeout=0.0) is None:
                break  # caps cause expected drops at P4/P5

    return _measure("scheduler.submit+pop", spec.n_total + n_edges, run)


# ── Bench 3: log emit + replay_since ────────────────────────────────────


def bench_log(spec: WorkloadSpec) -> dict:
    """N emits + replay_since. When N exceeds the 500k ring cap, the
    baseline drops out and replay returns the gap signal — by-design."""
    log_reset()
    payload = b"id: 0\nevent: slot\ndata: x|0.0|0.0|domain|d0\n\n"
    n = spec.n_total

    def run() -> None:
        for _ in range(n):
            emit("slot", payload)
        replay_since(0)  # exercises the gap path when ring overflowed

    return _measure("log.emit+replay_since", n, run)


# ── Bench 4: integration (scheduler -> log -> wire) ─────────────────────


def bench_integration(spec: WorkloadSpec) -> dict:
    """Full pipeline (submit -> pop -> format_{slot,edge} -> emit) in
    bounded BATCH waves so scheduler caps are respected."""
    kinds = synthesize_kinds(spec)
    anchors, *_ = precompute_anchors(spec.n_domains)
    sched = PriorityScheduler()
    log_reset()
    n_edges = spec.n_total * 4
    total = spec.n_total + n_edges
    sample_edge = EdgeDelta(source_id="src", target_id="tgt", kind="calls")
    nd, BATCH = spec.n_domains, 4096
    edges_per_node = n_edges // max(spec.n_total, 1)
    ep = priority_for_edge()

    def drain(seq: int) -> int:
        while True:
            got = sched.pop(timeout=0.0)
            if got is None:
                return seq
            pri, item = got
            seq += 1
            if pri <= 4:
                i, kind = item  # type: ignore[misc]
                a = anchors[i % nd]
                emit(
                    "slot",
                    format_slot(
                        seq,
                        _WireSlot(
                            node_id=f"n{i}",
                            x=a[0],
                            y=a[1],
                            kind=kind,
                            domain_id=f"d{i % nd}",
                        ),
                    ),
                )
            else:
                emit("edge", format_edge(seq, sample_edge))

    def run() -> None:
        seq, edge_remaining = 0, n_edges
        for bs in range(0, spec.n_total, BATCH):
            for i in range(bs, min(bs + BATCH, spec.n_total)):
                sched.submit(priority_for_node(kinds[i]), (i, kinds[i]))
                for _e in range(edges_per_node):
                    if edge_remaining <= 0:
                        break
                    sched.submit(ep, edge_remaining)
                    edge_remaining -= 1
            seq = drain(seq)
        drain(seq)

    base = emit("probe", b"") - 1
    result = _measure("pipeline.scheduler+log+wire", total, run)
    result["log_retained"] = len(replay_since(base)[0])
    result["sched_dropped"] = sum(sched.stats()["dropped"].values())
    return result


# ── Reporter ────────────────────────────────────────────────────────────


def _fmt(r: dict) -> str:
    return (
        f"  {r['label']:<32} n={r['n']:>10,} {r['ns_per_op']:>10,.1f} ns/op"
        f"  {r['ops_per_sec']:>14,.0f} ops/sec"
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="bench_layout_authority")
    p.add_argument("--n", type=int, default=1_000_000, help="node count")
    spec = WorkloadSpec(n_total=p.parse_args(argv).n)
    print(f"Workload: N={spec.n_total:,} nodes, {spec.n_total * 4:,} edges")
    print(
        f"  domains={spec.n_domains}  tool_hubs={spec.n_tool_hubs}  "
        f"files={spec.n_files:,}  symbols={spec.n_symbols:,}  "
        f"memories={spec.n_memories:,}  entities={spec.n_entities:,}  "
        f"discussions={spec.n_discussions:,}  pad={spec.padding():,}\n"
    )
    results = [fn(spec) for fn in (bench_geometry, bench_scheduler, bench_log)]
    print("Component benchmarks:")
    for r in results:
        print(_fmt(r))  # noqa: E701
    print("\nIntegration benchmark:")
    integ = bench_integration(spec)
    print(_fmt(integ))
    print(
        f"    log retained: {integ['log_retained']:,} events  "
        f"scheduler dropped: {integ['sched_dropped']:,} items"
    )
    bn = max(results, key=lambda x: x["ns_per_op"])
    print(f"\nComponent bottleneck: {bn['label']} ({bn['ns_per_op']:.1f} ns/op)")
    return 0


if __name__ == "__main__":
    sys.exit(main())  # noqa: E701
