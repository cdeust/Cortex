"""Private cooldown roots prevent tests and separate installs sharing state."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mcp_server.shared.hook_state_paths import cooldown_path


class TestHookStatePaths(unittest.TestCase):
    def test_unset_or_blank_override_preserves_legacy_path_without_io(self) -> None:
        for override in (None, "", " "):
            environment = {} if override is None else {"CORTEX_CLAUDE_DIR": override}
            with patch.dict(os.environ, environment, clear=True):
                self.assertEqual(
                    cooldown_path("fixture.json"), Path("/tmp/fixture.json")
                )

    def test_actual_hooks_create_and_read_only_the_explicit_root(self) -> None:
        code = """
import os
from pathlib import Path
from mcp_server.hooks import pipeline_impact_bump, preemptive_context
root = Path(os.environ["CORTEX_CLAUDE_DIR"])
assert not root.exists(), "imports must not create cooldown directories"
for hook in (pipeline_impact_bump, preemptive_context):
    assert hook._COOLDOWN_FILE.parent == root / "methodology/hook-cooldowns"
    assert not hook._check_cooldown("fixture.py")
    hook._update_cooldown("fixture.py")
    assert hook._check_cooldown("fixture.py")
    assert hook._COOLDOWN_FILE.is_file()
"""
        with tempfile.TemporaryDirectory(prefix="cortex-cooldown-root-") as directory:
            for name in ("first", "second"):
                environment = dict(
                    os.environ, CORTEX_CLAUDE_DIR=str(Path(directory) / name)
                )
                result = subprocess.run(
                    [sys.executable, "-S", "-c", code],
                    cwd=Path(__file__).resolve().parents[2],
                    env=environment,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
