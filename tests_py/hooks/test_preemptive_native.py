"""Native read events must preserve project boundaries (ADR-1086)."""

from unittest.mock import patch

import pytest

from mcp_server.hooks import preemptive_context as hook


@pytest.mark.parametrize(
    "command",
    ['cat "src/a b.py"', "sed -n '1,20p' 'src/a b.py'", 'rg marker "src/a b.py"'],
)
def test_native_shell_reads_prime_exact_project_path(tmp_path, monkeypatch, command):
    target = tmp_path / "src/a b.py"
    target.parent.mkdir()
    target.write_text("marker\n")
    monkeypatch.delenv("CLAUDE_PROJECT_ROOT", raising=False)
    monkeypatch.setattr(hook, "_COOLDOWN_FILE", tmp_path / "cooldown.json")
    event = {
        "hook_event_name": "PostToolUse",
        "tool_name": "Bash",
        "cwd": str(tmp_path),
        "tool_input": {"command": command},
        "tool_response": {"exit_code": 0},
    }
    with patch.object(hook, "_prime_file_memories", return_value=1) as prime:
        hook.process_event(event)
    prime.assert_called_once_with(str(target), str(tmp_path))
