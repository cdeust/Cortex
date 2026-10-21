"""Session-scoped autouse fixtures every test session gets, re-exported for
``conftest.py`` (which sits at the file-size cap): the process leak guard and the
embedding download opt-out.

source: this PR
"""

from __future__ import annotations

from tests_py._broker_mode_session import (
    _in_process_store_when_marked,
    _stop_session_brokers,
)
from tests_py._embedding_opt_out import _embedding_zero_download
from tests_py._process_leak_guard import _session_process_leak_guard

__all__ = [
    "_embedding_zero_download",
    "_in_process_store_when_marked",
    "_session_process_leak_guard",
    "_stop_session_brokers",
]
