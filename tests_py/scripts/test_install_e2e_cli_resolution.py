"""npm Windows shim layouts, exercised as filesystem fixtures on the test host.

Source: npm folders documentation: local node_modules/.bin, global prefix.
https://docs.npmjs.com/cli/v11/configuring-npm/folders#executables
Actual Windows execution remains a hosted installation check.
"""

import json
from itertools import product
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.install_e2e import host


def installation(root: Path, layout: str, relative: str):
    if layout.startswith("local"):
        modules = root / (
            "NODE_MODULES" if layout.endswith("uppercase") else "node_modules"
        )
        shim = (
            modules
            / (".BIN" if layout.endswith("uppercase") else ".bin")
            / "claude.cmd"
        )
    else:
        prefix = root / ".bin" if layout == "global-bin-named-prefix" else root
        modules, shim = prefix / "node_modules", prefix / "claude.cmd"
    shim.parent.mkdir(parents=True, exist_ok=True)
    shim.touch()
    package = modules / "@anthropic-ai/claude-code"
    entry = package / relative
    entry.parent.mkdir(parents=True, exist_ok=True)
    entry.touch()
    (package / "package.json").write_text(json.dumps({"bin": {"claude": relative}}))
    return shim, entry


def checked_resolution(layout: str, relative: str):
    with tempfile.TemporaryDirectory(prefix="npm with spaces ") as directory:
        root = Path(directory)
        shim, entry = installation(root, layout, relative)
        answers = [str(shim), str(root / "system-node.exe")]
        with patch.object(host.shutil, "which", side_effect=answers) as which:
            command = host._claude_command()
        expected = (str(entry.resolve()),)
        if relative.endswith(".js"):
            expected = (answers[1], *expected)
        return command, expected, which.call_args_list


class NpmCliResolution(unittest.TestCase):
    def test_selected_local_and_global_shims_resolve_their_own_native_or_js_entry(self):
        layouts = ("global", "global-bin-named-prefix", "local", "local-uppercase")
        for layout, relative in product(layouts, ("bin/claude.exe", "cli.js")):
            with self.subTest(layout=layout, entry=relative):
                command, expected, calls = checked_resolution(layout, relative)
                self.assertEqual(command, expected)
                self.assertEqual(calls[0].args, ("claude",))
                self.assertEqual(len(calls), 2 if relative.endswith(".js") else 1)

    def test_local_manifest_entry_cannot_escape_its_selected_package(self):
        with tempfile.TemporaryDirectory() as directory:
            shim, entry = installation(Path(directory), "local", "bin/claude.exe")
            package = entry.parent.parent
            (package / "package.json").write_text(
                json.dumps({"bin": {"claude": "../../outside.exe"}})
            )
            with (
                patch.object(host.shutil, "which", return_value=str(shim)),
                self.assertRaisesRegex(RuntimeError, "outside"),
            ):
                host._claude_command()

    def test_native_path_still_uses_its_real_target(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable = root / "real-cli"
            executable.touch()
            link = root / "claude"
            link.symlink_to(executable)
            with patch.object(host.shutil, "which", return_value=str(link)):
                self.assertEqual(host._claude_command(), (str(executable.resolve()),))


if __name__ == "__main__":
    unittest.main()
