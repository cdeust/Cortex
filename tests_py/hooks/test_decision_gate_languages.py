"""The decision gate judges every comment-marker language, every path.

Owner ruling of 2026-09-10 (ADR-1060, revision "no exception"): a run of
eight or more consecutive comment lines is refused whether it is written
with ``#``, ``//``, ``/* */``, ``--`` or ``;``, whether the file is a test,
and whether the run sits at the top of the file. What stays is the lexical
reading: a string literal never reads as a comment.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from mcp_server.hooks import _decision_gate_lex as lex
from mcp_server.hooks import decision_gate as gate

ALLOW, BLOCK = 0, 2
REPO_ROOT = Path(__file__).resolve().parents[2]


def _prose(lines: int, marker: str) -> str:
    return "\n".join(f"{marker} rationale line {n}" for n in range(lines))


def _edit(path: Path, old: str, new: str) -> dict:
    return {
        "tool_name": "Edit",
        "tool_input": {"file_path": str(path), "old_string": old, "new_string": new},
    }


def _write(path: Path, content: str) -> dict:
    return {
        "tool_name": "Write",
        "tool_input": {"file_path": str(path), "content": content},
    }


def _rust_test_file(tmp_path: Path) -> Path:
    """The file shape that leaked on 2026-09-10: a ``tests/*.rs`` file."""
    root = tmp_path / "tests"
    root.mkdir()
    path = root / "rust_local_receiver_static_resolution.rs"
    path.write_text("use std::path::Path;\n\n#[test]\nfn anchor() {}\n", "utf-8")
    return path


def test_refuses_a_doc_comment_block_in_a_rust_test_file(tmp_path: Path) -> None:
    """Six lines of ``///`` rationale passed on 2026-09-10 because the file
    was under ``tests/``, the language used ``//`` markers, and nothing
    executable preceded the run. None of the three is an exemption now."""
    path = _rust_test_file(tmp_path)
    event = _edit(path, "#[test]", _prose(10, "///") + "\n#[test]")
    assert gate.evaluate(event) == BLOCK


def test_the_process_entrypoint_refuses_the_rust_test_file(tmp_path: Path) -> None:
    """The owner's simulation, a PreToolUse event on stdin, through the
    hook's process entry point. ``scripts/launcher.py`` adds only a
    dependency install into ``deps/`` before ``runpy`` reaches this same
    ``__main__``; a unit test must not perform that install."""
    path = _rust_test_file(tmp_path)
    event = _edit(path, "#[test]", _prose(10, "///") + "\n#[test]")
    done = subprocess.run(
        [sys.executable, "-m", "mcp_server.hooks.decision_gate"],
        input=json.dumps(event),
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert done.returncode == BLOCK, done.stderr
    assert "would add 10 consecutive comment lines" in done.stderr
    assert "`// source: ADR-NNNN`" in done.stderr


@pytest.mark.parametrize("suffix", [".ts", ".go"])
def test_refuses_a_line_comment_block(tmp_path: Path, suffix: str) -> None:
    path = tmp_path / f"thing{suffix}"
    path.write_text("var first = 0\nvar anchor = 1\n", "utf-8")
    event = _edit(path, "var anchor = 1", _prose(10, "//") + "\nvar anchor = 1")
    assert gate.evaluate(event) == BLOCK


def test_refuses_a_block_comment_in_java(tmp_path: Path) -> None:
    """Every line a ``/* */`` block crosses is a comment line."""
    path = tmp_path / "Thing.java"
    path.write_text("class Thing {\n    int anchor = 1;\n}\n", "utf-8")
    body = "\n".join(f"     * rationale line {n}" for n in range(8))
    block = f"    /*\n{body}\n     */\n    int anchor = 1;"
    assert gate.evaluate(_edit(path, "    int anchor = 1;", block)) == BLOCK


def test_refuses_a_header_block_on_a_new_python_file(tmp_path: Path) -> None:
    """A licence or orientation block at the top of a file is judged like
    any other run: the header is not exempt."""
    content = "#!/usr/bin/env python3\n" + _prose(10, "#") + "\nimport os\n"
    assert gate.evaluate(_write(tmp_path / "new_mod.py", content)) == BLOCK


def test_a_rust_string_holding_slash_slash_text_is_code(tmp_path: Path) -> None:
    path = tmp_path / "thing.rs"
    path.write_text("fn main() {\n    let anchor = 1;\n}\n", "utf-8")
    text = "\n".join(f"// not a comment, line {n}" for n in range(10))
    literal = f'    let s = "\n{text}\n";\n    let anchor = 1;'
    assert gate.evaluate(_edit(path, "    let anchor = 1;", literal)) == ALLOW


def test_a_block_comment_inside_a_rust_string_is_not_a_comment(tmp_path: Path) -> None:
    path = tmp_path / "thing.rs"
    path.write_text("fn main() {\n    let anchor = 1;\n}\n", "utf-8")
    body = "\n".join(f" * not a comment, line {n}" for n in range(10))
    literal = f'    let s = r#"/*\n{body}\n */"#;\n    let anchor = 1;'
    assert gate.evaluate(_edit(path, "    let anchor = 1;", literal)) == ALLOW


def test_allows_a_run_one_line_under_the_limit(tmp_path: Path) -> None:
    path = tmp_path / "thing.rs"
    path.write_text("fn main() {}\n", "utf-8")
    event = _edit(path, "fn main() {}", _prose(gate.PROSE_RUN_LIMIT - 1, "//"))
    assert gate.evaluate(event) == ALLOW


def test_grandfathers_a_block_already_in_a_go_file(tmp_path: Path) -> None:
    """Only what the call introduces is judged, so a legacy file with a long
    header stays editable."""
    path = tmp_path / "thing.go"
    path.write_text(_prose(12, "//") + "\npackage thing\n\nvar anchor = 1\n", "utf-8")
    assert gate.evaluate(_edit(path, "var anchor = 1", "var anchor = 2")) == ALLOW


def test_pointer_lines_never_count(tmp_path: Path) -> None:
    path = tmp_path / "thing.ts"
    path.write_text("const anchor = 1;\n", "utf-8")
    pointers = "\n".join(f"// source: ADR-{1000 + n}" for n in range(20))
    assert gate.evaluate(_edit(path, "const anchor = 1;", pointers)) == ALLOW


def test_override_releases_the_gate(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "Thing.java"
    path.write_text("class Thing {}\n", "utf-8")
    event = _edit(path, "class Thing {}", _prose(20, "//"))
    assert gate.evaluate(event) == BLOCK
    monkeypatch.setenv("CORTEX_DECISION_GATE", "off")
    assert gate.evaluate(event) == ALLOW


@pytest.mark.parametrize("suffix", sorted(lex.LANGUAGES))
def test_every_declared_suffix_is_enforced(tmp_path: Path, suffix: str) -> None:
    """The suffix table and the scanner table are one table: a suffix the
    gate names is a suffix the gate refuses, in that suffix's own marker."""
    marker = lex.LANGUAGES[suffix].marker
    content = _prose(10, marker) + "\n"
    assert gate.evaluate(_write(tmp_path / f"thing{suffix}", content)) == BLOCK


def test_suffix_match_is_case_insensitive(tmp_path: Path) -> None:
    content = _prose(10, "//") + "\n"
    assert gate.evaluate(_write(tmp_path / "Thing.RS", content)) == BLOCK


def test_a_rust_lifetime_does_not_swallow_the_next_comment() -> None:
    """``'a`` is not a character literal; treating it as one opened a string
    that hid every comment until the next apostrophe."""
    text = "fn f<'a>(x: &'a str) {}\n// real\nlet c = '\\'';\n// real too\n"
    assert lex.LANGUAGES[".rs"].scan(text) == {2, 4}


def test_an_unterminated_block_comment_runs_to_the_end_of_the_file() -> None:
    assert lex.LANGUAGES[".c"].scan("int x;\n/* open\nline\n") == {2, 3, 4}


def test_a_trailing_comment_on_a_code_line_is_not_a_comment_line() -> None:
    assert lex.LANGUAGES[".py"].scan("x = 1  # trailing\n# full\ny = '# no'\n") == {2}
    assert lex.LANGUAGES[".go"].scan("x := 1 // trailing\n// full\n") == {2}


def test_the_refusal_names_the_language_marker(tmp_path: Path, capsys) -> None:
    path = tmp_path / "schema.sql"
    path.write_text("SELECT 1;\n", "utf-8")
    assert gate.evaluate(_edit(path, "SELECT 1;", _prose(10, "--"))) == BLOCK
    assert "`-- source: ADR-NNNN`" in capsys.readouterr().err
