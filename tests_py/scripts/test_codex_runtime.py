"""No event-time dependency resolution. Source: native failure, 2026-10-02."""

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "plugins/hypermnesia-mcp-codex/scripts/runtime.py"
)
spec = importlib.util.spec_from_file_location("codex_runtime", SCRIPT)
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


def installed(tmp_path, version):
    root = tmp_path / "hypermnesia-mcp"
    metadata = (
        root / f"lib/python3/site-packages/hypermnesia_mcp-{version}.dist-info/METADATA"
    )
    metadata.parent.mkdir(parents=True)
    metadata.write_text(f"Name: hypermnesia-mcp\nVersion: {version}\n")
    python = root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    python.parent.mkdir(parents=True)
    python.touch()
    return python


def test_missing_runtime_fails_with_setup_instruction(tmp_path):
    with patch.object(runtime.subprocess, "check_output", return_value=str(tmp_path)):
        with pytest.raises(RuntimeError, match="setup"):
            runtime.installed_python("4.23.5")


def test_wrong_version_refuses_stale_tool(tmp_path):
    installed(tmp_path, "4.23.4")
    with patch.object(runtime.subprocess, "check_output", return_value=str(tmp_path)):
        with pytest.raises(RuntimeError, match="differs"):
            runtime.installed_python("4.23.5")


def test_matching_runtime_runs_without_install_or_resolve(tmp_path):
    python = installed(tmp_path, "4.24.0")
    with (
        patch.object(runtime.sys, "argv", [str(SCRIPT), "post_tool_capture"]),
        patch.object(runtime.subprocess, "check_output", return_value=str(tmp_path)),
        patch.object(runtime.subprocess, "run") as run,
        patch.object(runtime.os, "execv") as execute,
    ):
        if os.name == "nt":
            run.return_value.returncode = 0
            with pytest.raises(SystemExit) as result:
                runtime.main()
            assert result.value.code == 0
            execute.assert_not_called()
            run.assert_called_once()
            argv = run.call_args.args[0]
        else:
            runtime.main()
            run.assert_not_called()
            execute.assert_called_once()
            assert execute.call_args.args[0] == str(python)
            argv = execute.call_args.args[1]
    assert argv[:2] == [str(python), "-I"]
    assert argv[-1] == "post_tool_capture"


# Substitute the prepared interpreter lookup, then run the real wheel entry.
HOOK_BOOTSTRAP = """
import runpy
import sys
from pathlib import Path

sys.argv = sys.argv[1:]
main = runpy.run_path(sys.argv[0])["main"]
main.__globals__["installed_python"] = lambda _: Path(sys.executable)
main()
"""


@pytest.mark.parametrize(("flags", "exit_code"), [((), 2), (("--no-deps",), 0)])
def test_hook_dispatch_preserves_stdin_and_exit_code(tmp_path, flags, exit_code):
    command = " ".join(
        ("pip", "install", "--require-hashes", *flags, "-r", "requirements.txt")
    )
    event = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Write",
        "tool_input": {"file_path": "scripts/setup.sh", "content": command},
        "cwd": str(tmp_path),
    }
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("CORTEX_") and key != "DATABASE_URL"
    }
    env.update(CORTEX_CLAUDE_DIR=str(tmp_path), CORTEX_MEMORY_STORE_BACKEND="sqlite")
    result = subprocess.run(
        [sys.executable, "-c", HOOK_BOOTSTRAP, str(SCRIPT), "no_deps_gate"],
        input=json.dumps(event),
        encoding="utf-8",
        capture_output=True,
        cwd=tmp_path,
        env=env,
        timeout=20,
        check=False,
    )
    assert result.returncode == exit_code, result.stderr
    if exit_code:
        assert "[no-deps-gate] BLOCKED" in result.stderr
    else:
        assert result.stderr == ""


def test_setup_uses_host_interpreter_and_binary_wheels():
    with (
        patch.object(runtime.sys, "argv", [str(SCRIPT), "setup"]),
        patch.object(runtime.subprocess, "run") as run,
        patch.object(runtime, "installed_python"),
    ):
        runtime.main()
    command = run.call_args.args[0]
    assert command[:3] == ["uv", "tool", "install"]
    assert command[command.index("--python") + 1] == runtime.sys.executable
    assert "--no-build" in command
    assert run.call_args.kwargs["check"] is True


def test_server_uses_the_same_isolated_interpreter(tmp_path):
    python = installed(tmp_path, "4.24.0")
    with (
        patch.object(runtime.sys, "argv", [str(SCRIPT), "server"]),
        patch.object(runtime.subprocess, "check_output", return_value=str(tmp_path)),
        patch.object(runtime.os, "execv") as execute,
    ):
        runtime.main()
    execute.assert_called_once_with(
        str(python), [str(python), "-I", "-m", "mcp_server"]
    )


def test_server_forwards_profile_arguments(tmp_path):
    installed(tmp_path, "4.24.0")
    with (
        patch.object(runtime.sys, "argv", [str(SCRIPT), "server", "--profile", "lean"]),
        patch.object(runtime.subprocess, "check_output", return_value=str(tmp_path)),
        patch.object(runtime.os, "execv") as execute,
    ):
        runtime.main()
    assert execute.call_args.args[1][-2:] == ["--profile", "lean"]
