"""End-to-end tests for a Codex ``apply_patch`` event through the console
entry point: it must reach each hook module in the same shape, and produce
the same outcome, as the equivalent Claude Edit/Write event would.

Split out of ``test_entry.py`` (which covers PR 1's launcher parity and
environment-resolution surface) along the seam between "does the entry
point dispatch a benign Claude event correctly" and "does it normalize and
dispatch a Codex ``apply_patch`` event correctly" -- two different
questions about two different inputs, kept in one file only because they
shared helpers before this split grew past the 300-line cap.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests_py.hooks.test_entry import REPO_ROOT, _isolated_env


def _run_entry(
    module: str, event: str, env: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "mcp_server.hooks.entry", module],
        input=event,
        capture_output=True,
        text=True,
        env=env,
        cwd=REPO_ROOT,
    )


def _update_patch_event(tmp_path: Path, old: str, new: str) -> str:
    target = tmp_path / "edited.py"
    target.write_text(old)
    old_line, new_line = old.rstrip("\n"), new.rstrip("\n")
    body = (
        f"*** Begin Patch\n*** Update File: edited.py\n@@\n"
        f"-{old_line}\n+{new_line}\n*** End Patch"
    )
    return json.dumps(
        {
            "hook_event_name": "PostToolUse",
            "cwd": str(tmp_path),
            "tool_name": "apply_patch",
            "tool_input": {"command": body},
            "tool_response": "",
        }
    )


def _equivalent_edit_event(tmp_path: Path, old: str, new: str) -> str:
    target = tmp_path / "edited.py"
    return json.dumps(
        {
            "hook_event_name": "PostToolUse",
            "cwd": str(tmp_path),
            "tool_name": "Edit",
            "tool_input": {
                "file_path": str(target),
                "old_string": old,
                "new_string": new,
            },
            "tool_response": "",
        }
    )


@pytest.mark.parametrize("module", ["preemptive_context", "pipeline_impact_bump"])
def test_apply_patch_posttooluse_matches_equivalent_edit_stdout(
    module: str, tmp_path: Path
) -> None:
    env = _isolated_env(tmp_path)
    patch_result = _run_entry(
        module, _update_patch_event(tmp_path, "before\n", "after\n"), env
    )
    edit_result = _run_entry(
        module, _equivalent_edit_event(tmp_path, "before\n", "after\n"), env
    )

    assert patch_result.returncode == edit_result.returncode
    assert patch_result.stdout == edit_result.stdout


_LONG_COMMENT_BLOCK = "\n".join(
    f"# reason line {n} for this design choice" for n in range(1, 9)
)


def _add_file_patch_event(tmp_path: Path, filename: str) -> str:
    lines = "\n".join(f"+{line}" for line in _LONG_COMMENT_BLOCK.splitlines())
    body = f"*** Begin Patch\n*** Add File: {filename}\n{lines}\n+x = 1\n*** End Patch"
    return json.dumps(
        {
            "hook_event_name": "PreToolUse",
            "cwd": str(tmp_path),
            "tool_name": "apply_patch",
            "tool_input": {"command": body},
        }
    )


def _equivalent_write_event(tmp_path: Path, filename: str) -> str:
    content = _LONG_COMMENT_BLOCK + "\nx = 1\n"
    return json.dumps(
        {
            "hook_event_name": "PreToolUse",
            "cwd": str(tmp_path),
            "tool_name": "Write",
            "tool_input": {"file_path": str(tmp_path / filename), "content": content},
        }
    )


def test_apply_patch_pretooluse_blocks_like_equivalent_write(tmp_path: Path) -> None:
    env = _isolated_env(tmp_path)
    patch_result = _run_entry(
        "decision_gate", _add_file_patch_event(tmp_path, "new_a.py"), env
    )
    write_result = _run_entry(
        "decision_gate", _equivalent_write_event(tmp_path, "new_b.py"), env
    )

    assert patch_result.returncode == 2
    assert write_result.returncode == 2
    assert patch_result.returncode == write_result.returncode
    assert "[decision-gate] BLOCKED" in patch_result.stderr
    assert "[decision-gate] BLOCKED" in write_result.stderr


def _malformed_patch_event(tmp_path: Path, hook_event_name: str) -> str:
    body = "*** Begin Patch\n*** Update File: missing.py\n@@\n-x\n+y\n*** End Patch"
    return json.dumps(
        {
            "hook_event_name": hook_event_name,
            "cwd": str(tmp_path),
            "tool_name": "apply_patch",
            "tool_input": {"command": body},
        }
    )


def test_malformed_patch_on_pretooluse_exits_2(tmp_path: Path) -> None:
    env = _isolated_env(tmp_path)
    result = _run_entry(
        "decision_gate", _malformed_patch_event(tmp_path, "PreToolUse"), env
    )
    assert result.returncode == 2
    assert result.stdout == ""
    assert "decision_gate" in result.stderr


def test_malformed_patch_on_posttooluse_exits_1_with_stderr(tmp_path: Path) -> None:
    env = _isolated_env(tmp_path)
    result = _run_entry(
        "post_tool_capture", _malformed_patch_event(tmp_path, "PostToolUse"), env
    )
    assert result.returncode == 1
    assert result.stdout == ""
    assert "post_tool_capture" in result.stderr
