"""Banner installation checks must not import the ML stack.

source: docs/verification/codex-session-start-query-20261002.md
"""

from __future__ import annotations

import builtins
from importlib.metadata import PackageNotFoundError
from unittest.mock import patch

import pytest

from mcp_server.hooks import session_start as hook


@pytest.mark.parametrize("installed", [True, False])
def test_banner_checks_distribution_without_loading_ml(installed):
    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name.split(".")[0] in {"sentence_transformers", "torch", "scipy", "sklearn"}:
            raise AssertionError(f"banner attempted heavy import: {name}")
        return original_import(name, *args, **kwargs)

    # Real metadata lookup is isolated from the developer's installed packages.
    error = None if installed else PackageNotFoundError("sentence-transformers")
    with (
        patch(
            "importlib.metadata.version", return_value="installed", side_effect=error
        ) as version,
        patch.object(builtins, "__import__", side_effect=guarded_import),
    ):
        context = hook._build_context(
            [], [{"id": 1, "content": "fixture", "domain": "", "heat": 0.5}], None
        )
    version.assert_called_once_with("sentence-transformers")
    assert "## Cortex Memory Context" in context
    assert ("not installed in this runtime" in context) is not installed
    assert "installing in the background" not in context
    assert "improve next session" not in context
