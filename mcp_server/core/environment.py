"""Composition-root injection seam for core's environment-variable reads.

core/ may not import os (docs/module-inventory.md, Dependency Rules table;
issue #560). Every core module that used to call ``os.environ.get``
directly now goes through ``read_environment_variable``/
``read_environment_float`` here instead. The real ``os.environ.get``
reader is registered by ``mcp_server.hooks.wiring.wire_composition_root``,
which every process entry point calls once (server, launcher, each hook,
benchmarks, scripts, the test session); tests_py/scripts/
test_composition_root_wiring_coverage.py enumerates them.

An unconfigured reader RAISES rather than degrading to "var unset"
(CLAUDE.md: no silent fallbacks). The 2026-09-16 incident this guards
against: ``benchmarks/lib/ablation_runner.py`` sets
``CORTEX_ABLATE_<NAME>=1`` in-process and calls a benchmark's
``run_benchmark`` directly, never importing any composition root: with a
silently-None-returning reader, every ablation measurement silently
measured the un-ablated system, invalidating the published evidence.

source: issue #560
"""

from __future__ import annotations

from collections.abc import Callable

EnvironmentReader = Callable[[str], "str | None"]
_READER: EnvironmentReader | None = None


def configure_core_environment_reader(reader: EnvironmentReader) -> None:
    """Composition-root hook: register the live environment-variable reader.

    Precondition: called once, at process/session startup, by a
    handler/server/test-conftest module (never by core).
    Postcondition: ``read_environment_variable`` subsequently calls
    ``reader(name)`` fresh on every invocation — the binding is frozen, the
    values it returns are not.

    source: issue #560
    """
    global _READER
    _READER = reader


def read_environment_variable(name: str) -> str | None:
    """Read one environment variable through the injected reader.

    Precondition: ``configure_core_environment_reader`` has already been
    called by this process's composition root.
    Postcondition: returns the reader's result for ``name`` (``None`` iff
    the variable is genuinely unset — a legitimate, expected outcome).
    Raises RuntimeError if no reader was ever configured: a missing
    composition root must fail loudly, not silently behave as though
    every flag were unset (CLAUDE.md: no silent fallbacks). See the
    module docstring for the incident this prevents.

    source: issue #560
    """
    if _READER is None:
        raise RuntimeError(
            f"core/environment.py: no environment reader configured — "
            f"call configure_core_environment_reader() at this process's "
            f"composition root before reading {name!r}"
        )
    return _READER(name)


def read_environment_float(name: str, default: float) -> float:
    """Read and parse a float-valued tuning knob.

    Precondition: same as ``read_environment_variable``.
    Postcondition: returns ``default`` when the variable is unset or its
    value does not parse as a float — a malformed tuning knob must never
    fail the caller (retrieval scoring, ablation thresholds). Still
    raises RuntimeError, via ``read_environment_variable``, if no reader
    was ever configured.

    source: issue #560
    """
    raw = read_environment_variable(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default
