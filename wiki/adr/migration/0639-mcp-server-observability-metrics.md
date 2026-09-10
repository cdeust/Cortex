---
title: "ADR-0639 — mcp_server/observability/metrics.py rationale"
status: accepted
source: mcp_server/observability/metrics.py
---

# ADR-0639 — mcp_server/observability/metrics.py

Migrated source rationale. The excerpts below are preserved verbatim from the source snapshot; historical identifiers inside quotations are not current identities.

## module — original line 3 (docstring)

````text
We emit the text-exposition format (Prometheus 0.0.4 spec) directly.
Adding prometheus_client as a dependency was rejected because it pulls
in a runtime server on port 9090 by default, which conflicts with
Cortex's single-port MCP stdio transport. Our emitter is ~60 lines,
covers the subset of metric types we actually need (counter, histogram,
gauge), and is testable without a scrape loop.
````

## module — original line 10 (docstring)

````text
Metrics exposed:
  cortex_tool_calls_total{tool, status}
    Counter — successful vs failed tool calls per tool name.
````

## module — original line 14 (docstring)

````text
  cortex_tool_duration_seconds{tool}
    Histogram — per-tool call latency (buckets: 0.01, 0.05, 0.1, 0.5, 1,
    5, 10, 30, 60, +Inf). Wired from safe_handler.
````

## module — original line 18 (docstring)

````text
  cortex_memories_total
    Gauge — current memory count (scraped from SELECT COUNT(*)).
````

## module — original line 21 (docstring)

````text
  cortex_pool_checkouts_total{pool}
    Counter — successful connection acquisitions per pool.
````

## module — original line 24 (docstring)

````text
  cortex_pool_timeouts_total{pool}
    Counter — acquisition timeouts per pool.
````

## module — original line 27 (docstring)

````text
Source:
  * Prometheus text format 0.0.4:
    https://prometheus.io/docs/instrumenting/exposition_formats/
  * docs/program/phase-5-pool-admission-design.md §7.

````
