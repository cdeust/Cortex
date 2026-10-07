"""Issue #659: a platform without the resident worker spools and detaches a drainer.

The branch is chosen by the capability test, never by catching a transport error,
and the hook never loads the handler (the import that costs seconds against the
hook's 10 s budget): it writes a file and starts a detached process.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from mcp_server.hooks import capture_dispatch, post_tool_capture as hook
from mcp_server.infrastructure import capture_peer, capture_spool
from tests_py.hooks.test_capture_worker_policy import payload

CONTENT = (
    "Bash: pytest tests_py/hooks -q\n"
    "3 failed, 41 passed: the capture worker refused a Windows interpreter "
    "and nothing was stored for two weeks of editing sessions."
)
STREAM = mock.sentinel.stream  # popen_options only forwards it
EXPECTED = {
    "content": CONTENT,
    "tags": ["auto-captured"],
    "directory": "/fixture",
    "source": "post_tool_capture",
    "origin_tool": "Bash",
    "write_class": "auto",
    "force": False,
}


@contextmanager
def _windows():
    # Scoped to the two modules that read the platform: a process-wide
    # sys.platform would also redirect unrelated lazy imports (msvcrt) that
    # this POSIX test host cannot load.
    fake = SimpleNamespace(platform="win32", executable=sys.executable)
    with (
        mock.patch.object(capture_dispatch, "sys", fake),
        mock.patch.object(capture_peer, "sys", fake),
    ):
        yield


class TestCapability(unittest.TestCase):
    def test_windows_is_reported_unsupported_without_raising(self):
        with _windows():
            self.assertFalse(capture_peer.is_supported())

    def test_missing_af_unix_is_unsupported_even_on_a_posix_name(self):
        with mock.patch.object(capture_peer, "socket", mock.Mock(spec=[])):
            self.assertFalse(capture_peer.is_supported())

    def test_linux_and_macos_keep_the_resident_worker(self):
        for name in ("linux", "darwin"):
            with mock.patch.object(capture_peer, "sys", SimpleNamespace(platform=name)):
                self.assertEqual(
                    capture_peer.is_supported(), hasattr(socket, "AF_UNIX")
                )

    @unittest.skipUnless(sys.platform == "win32", "native Windows only")
    def test_native_windows_is_unsupported(self):
        self.assertFalse(capture_peer.is_supported())

    def test_unsupported_platform_still_refuses_the_worker_transport(self):
        with _windows(), self.assertRaisesRegex(OSError, "requires Linux/macOS"):
            capture_peer.supported()


class TestPopenOptions(unittest.TestCase):
    def test_windows_detaches_through_creationflags_only(self):
        options = capture_dispatch.popen_options("win32", STREAM)
        # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP (Win32 process-creation flags)
        self.assertEqual(options["creationflags"], 0x00000008 | 0x00000200)
        for ignored_or_unsupported in ("start_new_session", "pass_fds"):
            self.assertNotIn(ignored_or_unsupported, options)

    def test_every_platform_closes_stdin_logs_output_and_inherits_the_environment(self):
        for name in ("win32", "linux", "darwin", "freebsd14"):
            options = capture_dispatch.popen_options(name, STREAM)
            self.assertTrue(options["close_fds"])
            self.assertIs(options["stdin"], subprocess.DEVNULL)
            self.assertIs(options["stdout"], STREAM)
            self.assertIs(options["stderr"], STREAM)
            self.assertEqual(options["env"], dict(os.environ))

    def test_posix_detaches_through_a_new_session(self):
        for name in ("linux", "darwin", "freebsd14"):
            options = capture_dispatch.popen_options(name, STREAM)
            self.assertIs(options["start_new_session"], True)
            self.assertNotIn("creationflags", options)


class TestHookOnUnsupportedPlatform(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        mock.patch.object(capture_dispatch, "CLAUDE_DIR", self.root).start()
        self.addCleanup(mock.patch.stopall)

    def _store(self):
        hook._store_memory("Bash", CONTENT, ["auto-captured"], "/fixture")

    def test_hook_spools_and_detaches_without_loading_the_handler(self):
        with (
            _windows(),
            mock.patch.object(
                hook, "_load_remember", side_effect=AssertionError("handler loaded")
            ),
            mock.patch.object(capture_dispatch, "deliver") as deliver,
            mock.patch.object(capture_dispatch.subprocess, "Popen") as popen,
            mock.patch.object(hook, "_log"),
        ):
            self._store()
        deliver.assert_not_called()
        spool = capture_spool.spool_directory(self.root)
        files = capture_spool.pending(spool)
        self.assertEqual([capture_spool.read(f) for f in files], [EXPECTED])
        popen.assert_called_once()
        command = popen.call_args.args[0]
        self.assertEqual(command[1:], ["-m", "mcp_server.hooks.capture_drain"])
        stream = popen.call_args.kwargs["stdout"]
        self.assertEqual(
            popen.call_args.kwargs, capture_dispatch.popen_options("win32", stream)
        )
        self.assertTrue(stream.closed)
        self.assertTrue((self.root / ".capture-worker" / "drain.log").exists())

    def test_a_stalled_backlog_is_reported_and_the_capture_still_queues(self):
        spool = capture_spool.spool_directory(self.root)
        old = capture_spool.write(spool, EXPECTED)
        long_ago = time.time() - capture_spool.STALL_SECONDS - 10
        os.utime(old, (long_ago, long_ago))
        with (
            _windows(),
            mock.patch.object(capture_dispatch.subprocess, "Popen"),
            mock.patch.object(capture_dispatch, "report_failure") as report,
            mock.patch.object(hook, "_log"),
        ):
            self._store()
        report.assert_called_once()
        self.assertEqual(report.call_args.kwargs["operation"], "capture_spool_stalled")
        self.assertEqual(len(capture_spool.pending(spool)), 2)

    def test_a_fresh_backlog_is_not_reported_as_stalled(self):
        spool = capture_spool.spool_directory(self.root)
        capture_spool.write(spool, EXPECTED)
        with (
            _windows(),
            mock.patch.object(capture_dispatch.subprocess, "Popen"),
            mock.patch.object(capture_dispatch, "report_failure") as report,
            mock.patch.object(hook, "_log"),
        ):
            self._store()
        report.assert_not_called()

    def test_spawn_failure_keeps_the_file_and_is_reported(self):
        with (
            _windows(),
            mock.patch.object(
                capture_dispatch.subprocess, "Popen", side_effect=OSError("no spawn")
            ),
            mock.patch.object(capture_dispatch, "report_failure") as report,
            mock.patch.object(hook, "_log"),
        ):
            self._store()
        self.assertEqual(
            len(capture_spool.pending(self.root / ".capture-worker" / "spool")), 1
        )
        self.assertIn("no spawn", report.call_args.args[0])

    def test_refused_payload_is_reported_and_never_spooled(self):
        with (
            _windows(),
            mock.patch.object(capture_dispatch.subprocess, "Popen") as popen,
            mock.patch.object(capture_dispatch, "report_failure") as report,
        ):
            self.assertFalse(
                capture_dispatch.dispatch({**payload(), "origin_tool": "Unknown"})
            )
        popen.assert_not_called()
        self.assertEqual(
            capture_spool.pending(capture_spool.spool_directory(self.root)), []
        )
        self.assertIn("unknown producing capture tool", report.call_args.args[0])

    def test_supported_platform_uses_the_worker_not_the_spool(self):
        with (
            mock.patch.object(capture_dispatch, "is_supported", return_value=True),
            mock.patch.object(capture_dispatch, "deliver") as deliver,
            mock.patch.object(capture_dispatch.subprocess, "Popen") as popen,
            mock.patch.object(hook, "_log"),
        ):
            self._store()
        deliver.assert_called_once()
        popen.assert_not_called()
        self.assertFalse((self.root / ".capture-worker").exists())


if __name__ == "__main__":
    unittest.main()
