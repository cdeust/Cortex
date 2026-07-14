"""Tests for mcp_server.infrastructure.otel_exporter (issue #122).

Covers:
  - OFF by default: no OTEL_EXPORTER_OTLP_ENDPOINT -> build_otel_exporter()
    returns None, regardless of whether the SDK is installed.
  - Graceful degradation: endpoint set but opentelemetry-sdk NOT
    importable -> returns None, logs exactly one warning (not per call).
  - Mapping: with the SDK mocked, OtelTelemetryExporter.export() maps a
    telemetry.record()-shaped sample onto the three cortex.* instruments
    with the documented attributes, and does not raise if an instrument
    call throws.
"""

from __future__ import annotations

import builtins
import sys
from types import ModuleType
from unittest.mock import MagicMock

import pytest

from mcp_server.infrastructure import otel_exporter


@pytest.fixture(autouse=True)
def _reset_warn_once_flag():
    otel_exporter._warned_once = False
    yield
    otel_exporter._warned_once = False


class TestOffByDefault:
    """No endpoint env var -> exporter is never built."""

    def test_no_endpoint_returns_none(self, monkeypatch):
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
        assert otel_exporter.build_otel_exporter() is None

    def test_empty_endpoint_returns_none(self, monkeypatch):
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
        assert otel_exporter.build_otel_exporter() is None


class TestDegradesWithoutSdk:
    """Endpoint set but opentelemetry-sdk not importable -> None + 1 warning."""

    def test_missing_sdk_returns_none_and_warns_once(self, monkeypatch, caplog):
        monkeypatch.setenv(
            "OTEL_EXPORTER_OTLP_ENDPOINT", "https://collector.example.com"
        )

        real_import = builtins.__import__

        def _blocking_import(name, *args, **kwargs):
            if name.startswith("opentelemetry"):
                raise ImportError(f"simulated missing SDK: {name}")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _blocking_import)

        with caplog.at_level("WARNING"):
            result = otel_exporter.build_otel_exporter()
            assert result is None
            result2 = otel_exporter.build_otel_exporter()
            assert result2 is None

        warnings = [r for r in caplog.records if r.levelname == "WARNING"]
        assert len(warnings) == 1
        assert "opentelemetry-sdk" in warnings[0].message


def _install_fake_opentelemetry_sdk(monkeypatch, meter: MagicMock) -> MagicMock:
    """Register a minimal fake `opentelemetry.*` package tree in sys.modules."""
    provider_cls = MagicMock(
        return_value=MagicMock(get_meter=MagicMock(return_value=meter))
    )

    otel_pkg = ModuleType("opentelemetry")
    sdk_pkg = ModuleType("opentelemetry.sdk")
    sdk_metrics_pkg = ModuleType("opentelemetry.sdk.metrics")
    sdk_metrics_pkg.MeterProvider = provider_cls
    sdk_metrics_export_pkg = ModuleType("opentelemetry.sdk.metrics.export")
    sdk_metrics_export_pkg.PeriodicExportingMetricReader = MagicMock()
    sdk_resources_pkg = ModuleType("opentelemetry.sdk.resources")
    sdk_resources_pkg.Resource = MagicMock(create=MagicMock(return_value=MagicMock()))

    exporter_pkg = ModuleType("opentelemetry.exporter")
    otlp_pkg = ModuleType("opentelemetry.exporter.otlp")
    proto_pkg = ModuleType("opentelemetry.exporter.otlp.proto")
    http_pkg = ModuleType("opentelemetry.exporter.otlp.proto.http")
    metric_exporter_pkg = ModuleType(
        "opentelemetry.exporter.otlp.proto.http.metric_exporter"
    )
    metric_exporter_pkg.OTLPMetricExporter = MagicMock()

    modules = {
        "opentelemetry": otel_pkg,
        "opentelemetry.sdk": sdk_pkg,
        "opentelemetry.sdk.metrics": sdk_metrics_pkg,
        "opentelemetry.sdk.metrics.export": sdk_metrics_export_pkg,
        "opentelemetry.sdk.resources": sdk_resources_pkg,
        "opentelemetry.exporter": exporter_pkg,
        "opentelemetry.exporter.otlp": otlp_pkg,
        "opentelemetry.exporter.otlp.proto": proto_pkg,
        "opentelemetry.exporter.otlp.proto.http": http_pkg,
        "opentelemetry.exporter.otlp.proto.http.metric_exporter": metric_exporter_pkg,
    }
    for name, mod in modules.items():
        monkeypatch.setitem(sys.modules, name, mod)
    return provider_cls


class TestBuildsWithSdkMocked:
    """Endpoint set + SDK importable (mocked) -> a live exporter is built."""

    def test_returns_exporter_wired_to_meter(self, monkeypatch):
        monkeypatch.setenv(
            "OTEL_EXPORTER_OTLP_ENDPOINT", "https://collector.example.com"
        )
        meter = MagicMock()
        _install_fake_opentelemetry_sdk(monkeypatch, meter)

        result = otel_exporter.build_otel_exporter()

        assert isinstance(result, otel_exporter.OtelTelemetryExporter)
        # Three instruments created against the fake meter, per docstring.
        assert meter.create_histogram.call_count == 2
        assert meter.create_counter.call_count == 1
        created_names = [c.args[0] for c in meter.create_histogram.call_args_list]
        assert "cortex.tool.duration" in created_names
        assert "cortex.recall.results" in created_names
        assert meter.create_counter.call_args.args[0] == "cortex.tool.calls"


class TestExportMapping:
    """OtelTelemetryExporter.export() maps sample fields to instruments."""

    def _build_exporter_with_mock_instruments(self):
        meter = MagicMock()
        duration = MagicMock()
        calls = MagicMock()
        results = MagicMock()
        meter.create_histogram.side_effect = [duration, results]
        meter.create_counter.return_value = calls
        exporter = otel_exporter.OtelTelemetryExporter(meter)
        return exporter, duration, calls, results

    def test_export_records_duration_and_calls(self):
        exporter, duration, calls, results = (
            self._build_exporter_with_mock_instruments()
        )

        exporter.export(
            {
                "op": "recall",
                "latency_ms": 12.5,
                "result_count": 4,
                "ok": True,
            }
        )

        duration.record.assert_called_once_with(
            12.5, {"tool": "recall", "status": "ok"}
        )
        calls.add.assert_called_once_with(1, {"tool": "recall", "status": "ok"})
        results.record.assert_called_once_with(4.0, {"tool": "recall", "status": "ok"})

    def test_export_maps_failure_status(self):
        exporter, duration, calls, results = (
            self._build_exporter_with_mock_instruments()
        )

        exporter.export({"op": "remember", "latency_ms": 3.0, "ok": False})

        calls.add.assert_called_once_with(1, {"tool": "remember", "status": "fail"})

    def test_export_skips_result_histogram_when_zero(self):
        exporter, duration, calls, results = (
            self._build_exporter_with_mock_instruments()
        )

        exporter.export({"op": "forget", "latency_ms": 1.0, "ok": True})

        results.record.assert_not_called()

    def test_export_swallows_instrument_exception(self):
        exporter, duration, calls, results = (
            self._build_exporter_with_mock_instruments()
        )
        duration.record.side_effect = RuntimeError("instrument down")

        # Must not raise -- telemetry must never break the calling tool.
        exporter.export({"op": "recall", "latency_ms": 1.0, "ok": True})
