"""No event-time dependency resolution. Source: native failure, 2026-10-02."""

import importlib.util
import os
from pathlib import Path
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


def test_matching_runtime_execs_without_install_or_resolve(tmp_path):
    python = installed(tmp_path, "4.23.5")
    with (
        patch.object(runtime.sys, "argv", [str(SCRIPT), "post_tool_capture"]),
        patch.object(runtime.subprocess, "check_output", return_value=str(tmp_path)),
        patch.object(runtime.subprocess, "run") as run,
        patch.object(runtime.os, "execv") as execute,
    ):
        runtime.main()
    run.assert_not_called()
    execute.assert_called_once()
    assert execute.call_args.args[0] == str(python)
    assert execute.call_args.args[1][-1] == "post_tool_capture"
    assert execute.call_args.args[1][1] == "-I"


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
    python = installed(tmp_path, "4.23.5")
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
    installed(tmp_path, "4.23.5")
    with (
        patch.object(runtime.sys, "argv", [str(SCRIPT), "server", "--profile", "lean"]),
        patch.object(runtime.subprocess, "check_output", return_value=str(tmp_path)),
        patch.object(runtime.os, "execv") as execute,
    ):
        runtime.main()
    assert execute.call_args.args[1][-2:] == ["--profile", "lean"]
