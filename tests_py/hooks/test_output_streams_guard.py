"""No hook entry point may print through the locale encoding (issue #688).

An AST predicate with negative tests, like ``test_stdin_guard`` for the input
side. A hook process that has a ``__main__`` block (or is the console entry
point) and writes to a standard stream must call ``use_utf8_output``, the one
place hooks decide their output encoding; nobody else may reconfigure a stream.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / "mcp_server" / "hooks"
PLUGIN_SCRIPTS = ROOT / "plugins" / "hypermnesia-mcp-codex" / "scripts"
LAUNCHER = ROOT / "scripts" / "launcher.py"
# The one place that may reconfigure a standard stream.
SHARED_PATH = "output_streams.py"
# Console entry points that run through a function, not a __main__ block.
FUNCTION_ENTRIES = {"entry.py": "main"}
CALL = "use_utf8_output"


def _is_main_block(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.If)
        and isinstance(node.test, ast.Compare)
        and isinstance(node.test.left, ast.Name)
        and node.test.left.id == "__name__"
        and any(
            isinstance(c, ast.Constant) and c.value == "__main__"
            for c in node.test.comparators
        )
    )


def _calls(node: ast.AST, name: str) -> bool:
    for call in ast.walk(node):
        if isinstance(call, ast.Call):
            func = call.func
            if (isinstance(func, ast.Name) and func.id == name) or (
                isinstance(func, ast.Attribute) and func.attr == name
            ):
                return True
    return False


def _call_line(node: ast.AST, name: str) -> int:
    """Line of the first call to ``name`` inside ``node``."""
    return min(
        call.lineno
        for call in ast.walk(node)
        if isinstance(call, ast.Call)
        and isinstance(call.func, (ast.Name, ast.Attribute))
        and (
            getattr(call.func, "id", None) == name
            or getattr(call.func, "attr", None) == name
        )
    )


def _writes_a_standard_stream(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == "print":
                return True
        if isinstance(node, ast.Attribute) and node.attr in {"stdout", "stderr"}:
            if isinstance(node.value, ast.Name) and node.value.id == "sys":
                return True
    return False


def _unredirected_prints(tree: ast.AST) -> list[int]:
    """Lines of ``print(...)`` without ``file=``: they go to stdout."""
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "print"
        and not any(k.arg == "file" for k in node.keywords)
    ]


def _reconfigure_lines(tree: ast.AST) -> list[int]:
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "reconfigure"
    ]


def entry_without_shared_path(path_name: str, source: str) -> bool:
    """True when ``source`` is an entry point that writes but skips the path."""
    tree = ast.parse(source)
    if not _writes_a_standard_stream(tree):
        return False
    function = FUNCTION_ENTRIES.get(path_name)
    if function is not None:
        return not any(
            isinstance(n, ast.FunctionDef) and n.name == function and _calls(n, CALL)
            for n in ast.walk(tree)
        )
    blocks = [n for n in ast.walk(tree) if _is_main_block(n)]
    return bool(blocks) and not any(_calls(b, CALL) for b in blocks)


def _hook_files() -> list[Path]:
    return sorted(p for p in HOOKS.glob("*.py") if p.name != SHARED_PATH)


def test_every_hook_entry_point_that_writes_uses_the_shared_output_path() -> None:
    offenders = [
        p.name
        for p in _hook_files()
        if entry_without_shared_path(p.name, p.read_text(encoding="utf-8"))
    ]
    assert not offenders, f"hook entry points writing without {CALL}(): {offenders}"


def test_the_guard_sees_the_entry_points_it_is_meant_to_cover() -> None:
    covered = [
        p.name
        for p in _hook_files()
        if "__main__" in p.read_text(encoding="utf-8")
        and _writes_a_standard_stream(ast.parse(p.read_text(encoding="utf-8")))
    ]
    assert {"auto_recall.py", "session_start.py", "decision_gate.py"} <= set(covered)


def test_no_hook_reconfigures_a_stream_outside_the_shared_path() -> None:
    offenders = {
        p.name: lines
        for p in _hook_files()
        if (lines := _reconfigure_lines(ast.parse(p.read_text(encoding="utf-8"))))
    }
    assert not offenders, f"stream reconfiguration outside {SHARED_PATH}: {offenders}"


def test_the_launcher_uses_the_shared_path_on_both_of_its_entry_functions() -> None:
    tree = ast.parse(LAUNCHER.read_text(encoding="utf-8"))
    functions = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert _calls(functions["main"], "_use_utf8_output")
    assert _calls(functions["entrypoint"], "_use_utf8_output")
    assert _calls(functions["_use_utf8_output"], CALL)
    first_output = _call_line(functions["entrypoint"], "_use_utf8_output")
    assert first_output < _call_line(functions["entrypoint"], "audit_startup")
    assert first_output < _call_line(functions["entrypoint"], "cli")
    assert not _reconfigure_lines(tree)


def test_the_installer_script_uses_the_shared_path_before_it_prints() -> None:
    """install-plugin.sh pipes scripts/setup.py through tee, so its stdout is a
    pipe with the locale encoding on Windows."""
    tree = ast.parse((ROOT / "scripts" / "setup.py").read_text(encoding="utf-8"))
    main = next(
        n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "main"
    )
    helper = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "_use_utf8_output"
    )
    assert _calls(helper, CALL)
    assert _call_line(main, "_use_utf8_output") < _call_line(main, "print")


def test_codex_plugin_scripts_write_only_to_stderr() -> None:
    """They are stdlib-only (they cannot import the shared path), so their
    stdout must stay empty; stderr already tolerates any character."""
    offenders = {
        p.name: lines
        for p in sorted(PLUGIN_SCRIPTS.glob("*.py"))
        if (lines := _unredirected_prints(ast.parse(p.read_text(encoding="utf-8"))))
    }
    assert not offenders, f"plugin scripts printing to stdout: {offenders}"


@pytest.mark.parametrize(
    ("name", "source", "fires"),
    [
        ("h.py", 'if __name__ == "__main__":\n    print("x")\n', True),
        (
            "h.py",
            'import sys\nif __name__ == "__main__":\n    sys.stdout.write("x")\n',
            True,
        ),
        (
            "h.py",
            'if __name__ == "__main__":\n    use_utf8_output()\n    print("x")\n',
            False,
        ),
        ("h.py", "def f():\n    print('x')\n", False),
        ("h.py", 'if __name__ == "__main__":\n    main()\n', False),
        ("entry.py", "def main():\n    print('x')\n", True),
        ("entry.py", "def main():\n    use_utf8_output()\n    print('x')\n", False),
    ],
)
def test_the_predicate_fires_on_each_bypass_and_only_on_those(
    name: str, source: str, fires: bool
) -> None:
    assert entry_without_shared_path(name, source) is fires


def test_the_stream_predicates_fire_on_their_bypass_patterns() -> None:
    assert _reconfigure_lines(ast.parse("sys.stdout.reconfigure(encoding='utf-8')"))
    assert _unredirected_prints(ast.parse("print('x')")) == [1]
    assert not _unredirected_prints(ast.parse("print('x', file=sys.stderr)"))


def _print_literals_outside(codec: str, tree: ast.AST) -> list[tuple[int, str]]:
    """``(line, character)`` for each print() string literal ``codec`` cannot encode."""
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        is_print = (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "print"
        )
        if not is_print:
            continue
        for part in ast.walk(node):
            if isinstance(part, ast.Constant) and isinstance(part.value, str):
                try:
                    part.value.encode(codec)
                except UnicodeEncodeError as exc:
                    found.append((node.lineno, part.value[exc.start : exc.end]))
    return found


def test_developer_scripts_print_only_characters_a_windows_pipe_encodes() -> None:
    """Scripts are not hooks and do not call the shared path, so their literal
    output must stay inside cp1252, the code page of a Windows pipe (a literal
    outside it crashed ``dump_snapshot.py`` on a piped stdout)."""
    offenders = {
        p.name: hits
        for p in sorted((ROOT / "scripts").glob("*.py"))
        if (hits := _print_literals_outside("cp1252", ast.parse(p.read_text("utf-8"))))
    }
    assert not offenders, f"print() literals cp1252 cannot encode: {offenders}"


def test_the_literal_predicate_fires_outside_the_code_page_only() -> None:
    assert _print_literals_outside("cp1252", ast.parse("print('a → b')")) == [(1, "→")]
    assert not _print_literals_outside("cp1252", ast.parse("print('a — b')"))
