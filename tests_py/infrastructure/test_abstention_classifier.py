"""Tests for the abstention classifier loader (infrastructure boundary).

source: issue #560 — core/abstention_gate.py must not import os/pathlib;
the filesystem cache lookup lives here instead.
"""

from __future__ import annotations

import builtins

import pytest

from mcp_server.infrastructure.abstention_classifier import (
    load_abstention_classifier,
)


class TestLoadAbstentionClassifier:
    def test_returns_none_when_package_missing(self) -> None:
        """cortex-beam-abstain is not installed in the dev/CI environment
        (verified: `import cortex_beam_abstain` raises ModuleNotFoundError
        here); loading must degrade to None rather than raise, matching
        core/abstention_gate.py's "no filtering" fallback contract."""
        assert load_abstention_classifier() is None

    def test_returns_none_on_unexpected_load_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A load failure other than ImportError (corrupt cache, bad
        checkpoint) must also degrade to None, not propagate."""
        real_import = builtins.__import__

        def _raising_import(name, *args, **kwargs):
            if name == "cortex_beam_abstain":
                raise RuntimeError("simulated corrupt model checkpoint")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _raising_import)
        assert load_abstention_classifier() is None
