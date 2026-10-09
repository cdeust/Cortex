"""Session fixture: no test starts the detached embedding-model download.

Without it the first embed on a machine without model weights runs
``embedding_downloads.trigger_background_*``, a detached
``sentence_transformers`` download that outlives the session (found by the
process leak guard on Linux, 2026-10-09). Tests that exercise the download path
unset the variable themselves through ``monkeypatch``.

source: ADR-0519 (CORTEX_EMBEDDING_ZERO_DOWNLOAD)
"""

from __future__ import annotations

import pytest


@pytest.fixture(scope="session", autouse=True)
def _embedding_zero_download():
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("CORTEX_EMBEDDING_ZERO_DOWNLOAD", "1")
        yield
