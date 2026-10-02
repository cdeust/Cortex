"""CI must prepare the wheel before driving the resolved Codex MCP command.

source: docs/verification/codex-hooks-20261002.md
"""

from pathlib import Path
import re
import subprocess
import sys

import yaml


REPO = Path(__file__).resolve().parents[2]


def _host_step() -> str:
    workflow = yaml.safe_load((REPO / ".github/workflows/ci.yml").read_text())
    return next(
        step["run"]
        for step in workflow["jobs"]["mcp-host-config"]["steps"]
        if step.get("name")
        == "Validate Claude, Gemini, and Codex configuration parsing"
    )


def test_native_host_step_is_valid_shell_and_resolves_plugin_command():
    step = _host_step()
    subprocess.run(["bash", "-n"], input=step, text=True, check=True)
    expression = next(
        code
        for code in re.findall(r"python -c '([^']*)'", step)
        if "arg.replace" in code
    )
    output = subprocess.check_output(
        [sys.executable, "-c", expression], cwd=REPO, text=True
    )
    command = output.splitlines()
    assert command == [
        "python3",
        str(REPO / "plugins/hypermnesia-mcp-codex/scripts/runtime.py"),
        "server",
    ]
    assert Path(command[1]).is_file()
    assert "${PLUGIN_ROOT}" not in output


def test_host_step_prepares_candidate_in_same_environment_as_verifier():
    step = _host_step()
    setup = step.index("uv tool install")
    verifier = step.index("python scripts/verify_mcp_hosts.py")
    assert setup < verifier
    for variable in ("UV_CACHE_DIR", "UV_TOOL_DIR", "UV_FIND_LINKS"):
        assert step.index(f"export {variable}=") < setup
    assert "--no-build" in step[setup:verifier]
    assert "hypermnesia-mcp[postgresql,sqlite] @ file://${candidate_wheel}" in step
    assert 's["transport"]["command"]=="python3"' in step
