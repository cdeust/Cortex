"""The decision gate refuses prose where a pointer belongs.

Each test states the shape it protects, because the gate is a heuristic and
its exemptions are the part most likely to be loosened by accident.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from mcp_server.hooks import decision_gate as gate

ALLOW, BLOCK = 0, 2


def _prose(lines: int, marker: str = "#") -> str:
    return "\n".join(f"{marker} rationale line {n}" for n in range(lines))


def _edit(path: Path, old: str, new: str) -> dict:
    return {
        "tool_name": "Edit",
        "tool_input": {"file_path": str(path), "old_string": old, "new_string": new},
    }


def _script(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "thing.sh"
    # `echo "start"` matters: it makes the body a body. A run with nothing
    # executable before it is the file header, which is exempt by design.
    path.write_text(
        f'#!/usr/bin/env bash\nset -euo pipefail\n\necho "start"\n{body}\n', "utf-8"
    )
    return path


def test_blocks_a_prose_block_added_to_a_script(tmp_path: Path) -> None:
    path = _script(tmp_path, 'echo "anchor"\n')
    event = _edit(
        path, 'echo "anchor"', _prose(gate.PROSE_RUN_LIMIT) + '\necho "anchor"'
    )
    assert gate.evaluate(event) == BLOCK


def test_allows_one_line_under_the_limit(tmp_path: Path) -> None:
    """The threshold is the rule; a shorter block is explanation, not a decision."""
    path = _script(tmp_path, 'echo "anchor"')
    block = _prose(gate.PROSE_RUN_LIMIT - 1)
    assert gate.evaluate(_edit(path, 'echo "anchor"', block)) == ALLOW


def test_allows_the_sanctioned_pointer_form(tmp_path: Path) -> None:
    path = _script(tmp_path, 'echo "anchor"')
    pointers = "\n".join(f"# source: ADR-{1000 + n}" for n in range(20))
    assert gate.evaluate(_edit(path, 'echo "anchor"', pointers)) == ALLOW


def test_allows_a_long_header_on_a_new_file(tmp_path: Path) -> None:
    """A header is orientation. It is exempt because nothing executable
    precedes it, not because of where its line number falls."""
    content = "#!/usr/bin/env bash\nset -e\n\n" + _prose(30) + "\necho hi\n"
    event = {
        "tool_name": "Write",
        "tool_input": {"file_path": str(tmp_path / "new.sh"), "content": content},
    }
    assert gate.evaluate(event) == ALLOW


def test_grandfathers_a_block_already_in_the_file(tmp_path: Path) -> None:
    """Editing an unrelated part of a legacy file must never be refused."""
    legacy = _script(tmp_path, _prose(12) + '\necho "anchor"')
    assert gate.evaluate(_edit(legacy, 'echo "anchor"', 'echo "changed"')) == ALLOW


def test_exempts_tests(tmp_path: Path) -> None:
    path = tmp_path / "test_thing.py"
    path.write_text("y = 0\nx = 1\n", "utf-8")
    assert gate.evaluate(_edit(path, "x = 1", _prose(20))) == ALLOW


def test_ignores_file_types_with_no_comment_marker(tmp_path: Path) -> None:
    """Markdown is where prose belongs; the gate must not touch the wiki."""
    path = tmp_path / "page.md"
    path.write_text("intro\nhello\n", "utf-8")
    assert gate.evaluate(_edit(path, "hello", _prose(20))) == ALLOW


def test_override_releases_the_gate(tmp_path: Path, monkeypatch) -> None:
    path = _script(tmp_path, 'echo "anchor"')
    event = _edit(path, 'echo "anchor"', _prose(20))
    assert gate.evaluate(event) == BLOCK
    monkeypatch.setenv("CORTEX_DECISION_GATE", "off")
    assert gate.evaluate(event) == ALLOW


def test_slash_slash_languages_are_covered(tmp_path: Path) -> None:
    path = tmp_path / "thing.ts"
    path.write_text("const first = 0;\nconst anchor = 1;\n", "utf-8")
    event = _edit(path, "const anchor = 1;", _prose(20, "//"))
    assert gate.evaluate(event) == BLOCK


def test_malformed_event_never_blocks() -> None:
    """A hook that crashes closed would make every edit impossible."""
    assert gate.evaluate({}) == ALLOW
    assert gate.evaluate({"tool_name": "Edit", "tool_input": {}}) == ALLOW


def test_entrypoint_exits_two_on_a_blocked_write(tmp_path: Path) -> None:
    """The exit code is the contract with Claude Code, not an internal detail."""
    path = _script(tmp_path, 'echo "anchor"')
    event = _edit(path, 'echo "anchor"', _prose(20))
    done = subprocess.run(
        [sys.executable, "-m", "mcp_server.hooks.decision_gate"],
        input=json.dumps(event),
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[2],
    )
    assert done.returncode == BLOCK
    assert "decision-gate" in done.stderr
