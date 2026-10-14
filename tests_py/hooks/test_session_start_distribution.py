"""The banner must not import the ML stack, nor judge semantic search itself.

How recall ranks is the status line's job (``session_start_status``): the
launcher knows whether the semantic-search job finished, the banner does not.

source: docs/verification/codex-session-start-query-20261002.md
source: ADR-1104
"""

from __future__ import annotations

import builtins
from unittest.mock import patch

from mcp_server.hooks import session_start_context as hook


def test_banner_builds_without_the_ml_stack_or_its_metadata():
    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name.split(".")[0] in {"sentence_transformers", "torch", "scipy", "sklearn"}:
            raise AssertionError(f"banner attempted heavy import: {name}")
        return original_import(name, *args, **kwargs)

    with (
        patch("importlib.metadata.version") as version,
        patch.object(builtins, "__import__", side_effect=guarded_import),
    ):
        context = hook._build_context(
            [], [{"id": 1, "content": "fixture", "domain": "", "heat": 0.5}], None
        )
    version.assert_not_called()
    assert "## Cortex Memory Context" in context
    assert "sentence-transformers" not in context
