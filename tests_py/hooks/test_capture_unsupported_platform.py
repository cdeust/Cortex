"""Issue #659: a platform without the resident worker stores through the same path.

The branch is chosen by the capability test, never by catching a transport error.
"""

from __future__ import annotations

import socket
import unittest
from types import SimpleNamespace
from unittest import mock

from mcp_server.hooks import capture_dispatch, post_tool_capture as hook
from mcp_server.infrastructure import capture_peer
from tests_py.hooks.test_capture_worker_policy import payload

CONTENT = (
    "Bash: pytest tests_py/hooks -q\n"
    "3 failed, 41 passed: the capture worker refused a Windows interpreter "
    "and nothing was stored for two weeks of editing sessions."
)


def _platform(name: str):
    # Scoped to capture_peer: a process-wide sys.platform would also redirect
    # unrelated lazy imports (msvcrt) that this POSIX test host cannot load.
    return mock.patch.object(capture_peer, "sys", SimpleNamespace(platform=name))


def _windows():
    return _platform("win32")


def _stored_rows() -> int:
    from mcp_server.infrastructure.memory_config import get_memory_settings
    from mcp_server.infrastructure.memory_store import get_shared_store

    settings = get_memory_settings()
    store = get_shared_store(settings.DB_PATH, settings.EMBEDDING_DIM)
    return store.count_memories()["total"]


class TestCapability(unittest.TestCase):
    def test_windows_is_reported_unsupported_without_raising(self):
        with _windows():
            self.assertFalse(capture_peer.is_supported())
            self.assertFalse(capture_dispatch.resident_worker_available())

    def test_missing_af_unix_is_unsupported_even_on_a_posix_name(self):
        with mock.patch.object(capture_peer, "socket", mock.Mock(spec=[])):
            self.assertFalse(capture_peer.is_supported())

    def test_linux_and_macos_keep_the_resident_worker(self):
        for name in ("linux", "darwin"):
            with _platform(name):
                self.assertEqual(
                    capture_peer.is_supported(), hasattr(socket, "AF_UNIX")
                )

    def test_unsupported_platform_still_refuses_the_worker_transport(self):
        with _windows(), self.assertRaisesRegex(OSError, "requires Linux/macOS"):
            capture_peer.supported()


class TestInProcessStore(unittest.TestCase):
    def test_simulated_windows_stores_a_memory_without_any_worker(self):
        before = _stored_rows()
        with (
            _windows(),
            mock.patch.object(capture_dispatch, "deliver") as deliver,
            mock.patch.object(hook, "_log") as log,
        ):
            hook._store_memory("Bash", CONTENT, ["auto-captured"], "/fixture")
        deliver.assert_not_called()
        self.assertEqual(_stored_rows(), before + 1)
        self.assertIn("captured Bash", log.call_args.args[0])

    def test_in_process_path_validates_like_the_worker(self):
        from mcp_server.hooks.capture_store import store_in_process

        with self.assertRaisesRegex(ValueError, "unknown producing capture tool"):
            store_in_process({**payload(), "origin_tool": "Unknown"})

    def test_supported_platform_uses_the_worker_not_the_handler(self):
        with (
            mock.patch.object(
                capture_dispatch, "resident_worker_available", return_value=True
            ),
            mock.patch.object(capture_dispatch, "dispatch", return_value=True) as send,
            mock.patch.object(
                hook, "_load_remember", side_effect=AssertionError("in-process")
            ),
            mock.patch.object(hook, "_log"),
        ):
            hook._store_memory("Bash", CONTENT, [], "/fixture")
        send.assert_called_once()


if __name__ == "__main__":
    unittest.main()
