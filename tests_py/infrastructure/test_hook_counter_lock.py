"""Counter lock protocol on native POSIX and the simulated Windows branch."""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, call, patch

from mcp_server.infrastructure import hook_counter_lock as native


def windows_module(fake_msvcrt):
    spec = importlib.util.spec_from_file_location(
        "counter_lock_windows_probe", native.__file__
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    with patch("sys.platform", "win32"):
        with patch.dict("sys.modules", {"msvcrt": fake_msvcrt}):
            spec.loader.exec_module(module)
    return module


class CounterLockProtocol(unittest.TestCase):
    def setUp(self):
        tree = tempfile.TemporaryDirectory(prefix="cortex-counter-lock-test-")
        self.addCleanup(tree.cleanup)
        self.path = Path(tree.name) / "counter.lock"

    def test_lock_file_survives_release(self):
        with native.counter_lock(self.path):
            self.assertTrue(self.path.exists())
        self.assertTrue(
            self.path.exists(), "removing an active lock path would split locks"
        )

    def test_windows_locks_and_unlocks_the_same_byte(self):
        fake = MagicMock()
        module = windows_module(fake)
        with module.counter_lock(self.path):
            fd = fake.locking.call_args.args[0]
        self.assertEqual(
            fake.locking.call_args_list,
            [call(fd, fake.LK_LOCK, 1), call(fd, fake.LK_UNLCK, 1)],
        )

    def test_windows_acquisition_error_closes_without_unlocking(self):
        fake = MagicMock()
        fake.locking.side_effect = OSError("CRT lock failed")
        module = windows_module(fake)
        with patch.object(module.os, "close", wraps=module.os.close) as closed:
            with self.assertRaisesRegex(OSError, "CRT lock failed"):
                with module.counter_lock(self.path):
                    self.fail("failed acquire must not enter transaction")
        self.assertEqual(fake.locking.call_count, 1)
        closed.assert_called_once()

    def test_transaction_exception_releases_windows_lock(self):
        fake = MagicMock()
        module = windows_module(fake)
        with self.assertRaisesRegex(RuntimeError, "transaction failed"):
            with module.counter_lock(self.path):
                raise RuntimeError("transaction failed")
        self.assertEqual(fake.locking.call_args.args[1], fake.LK_UNLCK)


if __name__ == "__main__":
    unittest.main()
