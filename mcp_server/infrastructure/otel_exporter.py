"""OTLP telemetry exporter (infrastructure) -- optional, OFF by default.

Implements the ``core.telemetry.TelemetryExporter`` port declared in the
core layer. Core never imports this module; the composition root
(mcp_server/__main__.py) imports it and wires it via
``telemetry.set_exporter(build_otel_exporter())`` at startup.

Activation:
  Set ``OTEL_EXPORTER_OTLP_ENDPOINT`` (the standard OTel SDK env var) to
  opt in. Absent that var, ``build_otel_exporter()`` returns ``None`` and
  nothing is wired -- the local, no-egress
  ``~/.claude/methodology/telemetry.jsonl`` sink (core/telemetry.py)
  remains the sole sink, preserving the default compliance posture: zero
  network egress unless the operator explicitly configures an endpoint.
  ``OTEL_SERVICE_NAME`` optionally overrides the reported service name
  (default ``cortex-mcp``).

Metric naming (issue #122 comment, cdeust/Cortex):
  Mirrors Claude Code's own ``cortex.*``-prefixed OTel convention so both
  sources coexist in one collector without name collisions. Every metric
  below is a direct mapping from an existing ``telemetry.record()`` field
  -- no new counters are invented:
    - cortex.tool.duration   (histogram, ms)     <- sample["latency_ms"]
    - cortex.tool.calls      (counter, {tool,status}) <- one per sample
    - cortex.recall.results  (histogram)          <- sample["result_count"]

Degradation:
  If ``opentelemetry-sdk`` (the optional ``[otel]`` extra) is not
  installed, ``build_otel_exporter()`` logs one warning (not per call)
  and returns ``None``. Telemetry export must never break a tool call --
  every ``export()`` call is wrapped defensively.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any

logger = logging.getLogger(__name__)

_warned_once = False
_warn_lock = threading.Lock()


def _warn_missing_sdk_once() -> None:
    """Log the missing-SDK degradation warning exactly once per process."""
    global _warned_once
    with _warn_lock:
        if _warned_once:
            return
        _warned_once = True
    logger.warning(
        "OTEL_EXPORTER_OTLP_ENDPOINT is set but opentelemetry-sdk is not "
        "installed. Install the optional extra to enable OTLP export: "
        "pip install 'hypermnesia-mcp[otel]'. Local telemetry.jsonl "
        "logging is unaffected."
    )


class OtelTelemetryExporter:
    """Adapts ``telemetry.record()`` samples to OTel metric instruments.

    precondition: ``meter`` is a live ``opentelemetry.metrics.Meter``.
    postcondition: each ``export()`` call records exactly one point on
                   each of the three cortex.* instruments below, tagged
                   with {tool: op, status: ok|fail}; an instrument error
                   is caught and logged at debug level, never raised.
    """

    def __init__(self, meter: Any) -> None:
        self._duration = meter.create_histogram(
            "cortex.tool.duration",
            unit="ms",
            description="Per-call latency of a Cortex MCP tool handler.",
        )
        self._calls = meter.create_counter(
            "cortex.tool.calls",
            description="Number of Cortex MCP tool handler invocations.",
        )
        self._results = meter.create_histogram(
            "cortex.recall.results",
            description="result_count reported by a Cortex MCP tool call.",
        )

    def export(self, sample: dict[str, Any]) -> None:
        op = str(sample.get("op", "unknown"))
        ok = bool(sample.get("ok", True))
        attributes = {"tool": op, "status": "ok" if ok else "fail"}
        try:
            self._duration.record(float(sample.get("latency_ms", 0.0)), attributes)
            self._calls.add(1, attributes)
            result_count = sample.get("result_count", 0)
            if result_count:
                self._results.record(float(result_count), attributes)
        except Exception:  # noqa: BLE001 — last-resort boundary — failure is logged; degraded mode continues
            # Telemetry export must never break the calling tool.
            logger.debug("OTLP metric export failed", exc_info=True)


def build_otel_exporter() -> OtelTelemetryExporter | None:
    """Build the OTLP exporter iff ``OTEL_EXPORTER_OTLP_ENDPOINT`` is set.

    precondition: none.
    postcondition: returns ``None`` when the env var is absent (default
                   OFF, zero behavior change from pre-#122 Cortex) or
                   when ``opentelemetry-sdk`` is not importable (logs one
                   warning via ``_warn_missing_sdk_once``). Otherwise
                   returns a live ``OtelTelemetryExporter`` backed by a
                   periodic-exporting OTLP metric pipeline; the SDK
                   resolves endpoint/headers/protocol from the standard
                   ``OTEL_EXPORTER_OTLP_*`` env vars itself.
    """
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        return None
    try:
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import (  # noqa: PLC0415 — optional-feature probe: ImportError here is a handled degraded mode
            OTLPMetricExporter,
        )
        from opentelemetry.sdk.metrics import MeterProvider  # noqa: PLC0415 — optional-feature probe: ImportError here is a handled degraded mode
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader  # noqa: PLC0415 — optional-feature probe: ImportError here is a handled degraded mode
        from opentelemetry.sdk.resources import Resource  # noqa: PLC0415 — optional-feature probe: ImportError here is a handled degraded mode
    except ImportError:
        _warn_missing_sdk_once()
        return None

    service_name = os.environ.get("OTEL_SERVICE_NAME", "cortex-mcp")
    resource = Resource.create({"service.name": service_name})
    reader = PeriodicExportingMetricReader(OTLPMetricExporter())
    provider = MeterProvider(resource=resource, metric_readers=[reader])
    meter = provider.get_meter("cortex.telemetry")
    return OtelTelemetryExporter(meter)
