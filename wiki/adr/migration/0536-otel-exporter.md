---
kind: adr
number: 0536
title: Preserve otel_exporter design decisions
status: accepted
---

# ADR-0536: otel_exporter design decisions

## Context

Canonical migration of decision evidence from `mcp_server/infrastructure/otel_exporter.py` under ADR-0056.
The excerpts below preserve historical claims and citations verbatim; original ADR numbers are historical quotations, not current identity bindings.

## Decision

Keep the source implementation linked to this versioned decision record. Operational API documentation remains with the implementation.

## Preserved decision evidence

### module, original line 1

````text
Implements the ``core.telemetry.TelemetryExporter`` port declared in the
core layer. Core never imports this module; the composition root
(mcp_server/__main__.py) imports it and wires it via
``telemetry.set_exporter(build_otel_exporter())`` at startup.
````

### module, original line 1

````text
Metric naming (issue #122 comment, cdeust/Cortex):
  Mirrors Claude Code's own ``cortex.*``-prefixed OTel convention so both
  sources coexist in one collector without name collisions. Every metric
  below is a direct mapping from an existing ``telemetry.record()`` field
  -- no new counters are invented:
    - cortex.tool.duration   (histogram, ms)     <- sample["latency_ms"]
    - cortex.tool.calls      (counter, {tool,status}) <- one per sample
    - cortex.recall.results  (histogram)          <- sample["result_count"]
````

### module, original line 1

````text
Degradation:
  If ``opentelemetry-sdk`` (the optional ``[otel]`` extra) is not
  installed, ``build_otel_exporter()`` logs one warning (not per call)
  and returns ``None``. Telemetry export must never break a tool call --
  every ``export()`` call is wrapped defensively.

````

### OtelTelemetryExporter, original line 63

````text
    precondition: ``meter`` is a live ``opentelemetry.metrics.Meter``.
    postcondition: each ``export()`` call records exactly one point on
                   each of the three cortex.* instruments below, tagged
                   with {tool: op, status: ok|fail}; an instrument error
                   is caught and logged at debug level, never raised.
    
````

### build_otel_exporter, original line 103

````text
    precondition: none.
    postcondition: returns ``None`` when the env var is absent (default
                   OFF, zero behavior change from pre-#122 Cortex) or
                   when ``opentelemetry-sdk`` is not importable (logs one
                   warning via ``_warn_missing_sdk_once``). Otherwise
                   returns a live ``OtelTelemetryExporter`` backed by a
                   periodic-exporting OTLP metric pipeline; the SDK
                   resolves endpoint/headers/protocol from the standard
                   ``OTEL_EXPORTER_OTLP_*`` env vars itself.
    
````

### comment, original line 98

````text
# Telemetry export must never break the calling tool.
````

## Consequences

Review rationale and source changes together. Historical evidence is preserved rather than silently rewritten; executable Python structure is unchanged after removing docstrings.
