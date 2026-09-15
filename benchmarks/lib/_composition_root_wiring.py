"""Benchmark composition-root bootstrap (issue #560).

Benchmarks never run through mcp_server/__main__.py or scripts/launcher.py,
so a benchmark entry point that reaches core imports this module for its
side effect (``import benchmarks.lib._composition_root_wiring  # noqa: F401``)
or calls ``wire_composition_root()`` itself. Both wire every core seam
through the one production function, mcp_server.hooks.wiring.
"""

from __future__ import annotations

from mcp_server.hooks.wiring import wire_composition_root

wire_composition_root()
