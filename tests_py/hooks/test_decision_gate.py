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


def test_slash_slash_languages_are_not_enforced(tmp_path: Path) -> None:
    """The marker table only covers ``#`` languages actually measured in the
    tracked tree (``.py``, ``.sh``, ``.bash``, ``.zsh``, ``.rb``); a zero-
    file threshold claim is not a threshold, it is a guess. ``//`` and
    ``/* */`` markers are dropped until they have tracked-tree evidence."""
    path = tmp_path / "thing.ts"
    path.write_text("const first = 0;\nconst anchor = 1;\n", "utf-8")
    event = _edit(path, "const anchor = 1;", _prose(20, "//"))
    assert gate.evaluate(event) == ALLOW


def test_malformed_event_never_blocks() -> None:
    """A hook that crashes closed would make every edit impossible."""
    assert gate.evaluate({}) == ALLOW
    assert gate.evaluate({"tool_name": "Edit", "tool_input": {}}) == ALLOW


def test_unreadable_current_file_never_crashes(tmp_path: Path) -> None:
    """A UnicodeDecodeError is a ValueError, not an OSError; catching only
    OSError around ``read_text`` crashed the hook (and every edit to the
    file) instead of allowing or refusing it. Reproduced pre-fix: exit
    ``'utf-8' codec can't decode byte 0xff``, not a clean 0 or 2."""
    path = tmp_path / "blob.py"
    path.write_bytes(b"\xff\xfe\x00\x01")
    event = _edit(str(path), "x", "y")
    assert gate.evaluate(event) == ALLOW  # must not raise


def test_a_leading_docstring_is_still_header(tmp_path: Path) -> None:
    """A module docstring followed by a licence block must not be blocked:
    nothing executable precedes either. Reproduced pre-fix: BLOCKED at
    line 3, because the docstring line disqualified the header scan even
    though it is not code."""
    content = (
        '"""Module docstring."""\n\n'
        + _prose(gate.PROSE_RUN_LIMIT)
        + "\n\ndef f():\n    pass\n"
    )
    event = {
        "tool_name": "Write",
        "tool_input": {"file_path": str(tmp_path / "new_mod.py"), "content": content},
    }
    assert gate.evaluate(event) == ALLOW


def test_a_heredoc_body_is_data_not_comments(tmp_path: Path) -> None:
    """Commented example lines inside a ``cat <<'CFG' ... CFG`` heredoc body
    are the data being written, not prose about the script. Reproduced
    pre-fix: BLOCKED at line 6."""
    path = _script(tmp_path, "")
    body = _prose(gate.PROSE_RUN_LIMIT)
    new = f"echo \"start\"\ncat <<'CFG' > out.conf\n{body}\nCFG\n"
    event = _edit(path, 'echo "start"', new)
    assert gate.evaluate(event) == ALLOW


def test_reflowing_a_grandfathered_block_is_not_an_introduction(tmp_path: Path) -> None:
    """Inserting or removing a bare marker line inside an already-present
    block must not flip its grandfathering: ADR-1060 says editing an
    unrelated part of a legacy file is never refused, and a rewrap of the
    same rationale is exactly that. Reproduced pre-fix: BLOCKED, because
    keying a run by its exact joined text changes the key on any reflow."""
    block = _prose(10)
    legacy = _script(tmp_path, block + '\necho "anchor"')
    reflowed_lines = block.split("\n")
    reflowed_lines.insert(5, "#")
    event = _edit(legacy, block, "\n".join(reflowed_lines))
    assert gate.evaluate(event) == ALLOW


def test_still_blocks_a_ten_to_twelve_line_rationale(tmp_path: Path) -> None:
    """Non-negotiable: the case the gate was built for. A worked rationale
    for a flag choice, added to a script, is still refused — a fix that
    lets this pass has removed the feature, not repaired it."""
    for length in (10, 12):
        path = _script(tmp_path, 'echo "anchor"')
        event = _edit(path, 'echo "anchor"', _prose(length) + '\necho "anchor"')
        assert gate.evaluate(event) == BLOCK, f"a {length}-line rationale must block"


def test_exempts_the_js_test_root(tmp_path: Path) -> None:
    """``tests_js`` is this repo's JS-equivalent of ``tests_py``; a Python
    test file was exempt while the same content under a JS test root was
    not, which is the inconsistency this closes."""
    root = tmp_path / "tests_js"
    root.mkdir()
    path = root / "spatial_hash.test.js"
    path.write_text("const x = 1;\n", "utf-8")
    assert gate.evaluate(_edit(path, "const x = 1;", _prose(20))) == ALLOW


def test_exempts_dot_spec_and_dot_test_filenames(tmp_path: Path) -> None:
    """A ``.spec.ts``/``.test.ts`` file narrates scenarios like a
    ``test_*.py`` file and must be exempt on that shape alone, independent
    of which directory it lives under."""
    path = tmp_path / "widget.spec.ts"
    path.write_text("const x = 1;\n", "utf-8")
    assert gate.evaluate(_edit(path, "const x = 1;", _prose(20))) == ALLOW


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


def test_entrypoint_never_crashes_on_an_unreadable_file(tmp_path: Path) -> None:
    """Through the real entry point, not just ``evaluate`` directly: a
    binary file under a code suffix must exit 0, never a Python traceback
    exit code, and never hang."""
    path = tmp_path / "blob.py"
    path.write_bytes(b"\xff\xfe\x00\x01")
    event = _edit(str(path), "x", "y")
    done = subprocess.run(
        [sys.executable, "-m", "mcp_server.hooks.decision_gate"],
        input=json.dumps(event),
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[2],
    )
    assert done.returncode == ALLOW
    assert done.stderr == ""
