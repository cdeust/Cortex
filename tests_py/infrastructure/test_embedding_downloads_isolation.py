"""The model-download child must not see user site-packages (issue #667)."""

from __future__ import annotations

import sys
from unittest import mock

from mcp_server.infrastructure import embedding_downloads


def test_the_model_download_child_runs_with_user_site_disabled(monkeypatch):
    monkeypatch.delenv("CORTEX_EMBEDDING_ZERO_DOWNLOAD", raising=False)
    with mock.patch.object(embedding_downloads, "_spawn_detached") as spawn:
        embedding_downloads.trigger_background_model_download("m", None, None)

    command = spawn.call_args.args[0]
    assert command[:3] == [sys.executable, "-s", "-c"]
