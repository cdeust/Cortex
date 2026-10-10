"""Siblings of the hook output fix: what else decodes or encodes by locale (#688).

source: ADR-1098 (supersedes the output half of ADR-0742)

Three AST guards and two real-process tests. A guard reads source: it proves a
call names its encoding, not what the child writes. The processes run with
``PYTHONIOENCODING=cp1252``, the stdout a Windows pipe has, on any platform.
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PLUGIN_SCRIPTS = ROOT / "plugins" / "hypermnesia-mcp-codex" / "scripts"
CALL = "use_utf8_output"


def _decodes_child_output(node: ast.Call) -> bool:
    """``text=True`` / ``universal_newlines=True``: subprocess decodes the pipe
    with the locale code page unless ``encoding=`` is named."""
    return any(
        k.arg in {"text", "universal_newlines"}
        and isinstance(k.value, ast.Constant)
        and k.value.value is True
        for k in node.keywords
    ) and not any(k.arg == "encoding" for k in node.keywords)


def _child_output_without_encoding(tree: ast.AST) -> list[int]:
    return [
        n.lineno
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and _decodes_child_output(n)
    ]


def _default_encoding_text_io(tree: ast.AST) -> list[int]:
    """Lines of read_text/write_text/os.fdopen text opens or text-decoded child
    output without ``encoding=``."""
    hits = _child_output_without_encoding(tree)
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        name = node.func.attr
        text_open = name in {"read_text", "write_text"} or (
            name == "fdopen"
            and not any(
                isinstance(a, ast.Constant) and "b" in str(a.value)
                for a in node.args[1:]
            )
        )
        if text_open and not any(k.arg == "encoding" for k in node.keywords):
            hits.append(node.lineno)
    return sorted(hits)


def _py(*roots: str) -> list[Path]:
    return sorted(p for r in roots for p in (ROOT / r).rglob("*.py"))


def test_codex_plugin_scripts_name_the_encoding_of_every_text_file() -> None:
    """They cannot import the shared path; the product's own text files are
    UTF-8, not the locale code page, and so is the output of ``uv``."""
    offenders = {
        p.name: lines
        for p in sorted(PLUGIN_SCRIPTS.glob("*.py"))
        if (lines := _default_encoding_text_io(ast.parse(p.read_text("utf-8"))))
    }
    assert not offenders, f"default-encoding text I/O in plugin scripts: {offenders}"
    assert _default_encoding_text_io(ast.parse("p.read_text()")) == [1]
    assert _default_encoding_text_io(ast.parse("os.fdopen(fd, 'w')")) == [1]
    assert not _default_encoding_text_io(ast.parse("os.fdopen(fd, 'wb')"))
    assert not _default_encoding_text_io(ast.parse("p.read_text(encoding='utf-8')"))


def test_product_code_names_the_encoding_of_decoded_child_output() -> None:
    """Every ``text=True`` subprocess call under mcp_server/ and plugins/."""
    offenders = {
        str(p.relative_to(ROOT)): lines
        for p in _py("mcp_server", "plugins")
        if (lines := _child_output_without_encoding(ast.parse(p.read_text("utf-8"))))
    }
    assert not offenders, f"child output decoded by locale: {offenders}"


@pytest.mark.parametrize(
    ("source", "hits"),
    [
        ("run(c, text=True)", [1]),
        ("check_output(c, universal_newlines=True)", [1]),
        ("run(c, text=True, encoding='utf-8')", []),
        ("run(c, capture_output=True)", []),
        ("run(c, text=False)", []),
    ],
)
def test_the_child_output_predicate_fires_only_without_an_encoding(
    source: str, hits: list[int]
) -> None:
    assert _child_output_without_encoding(ast.parse(source)) == hits


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


def _calls_shared_path(tree: ast.AST) -> bool:
    return any(
        isinstance(n, ast.Call) and getattr(n.func, "id", None) == CALL
        for n in ast.walk(tree)
    )


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


def test_product_modules_print_outside_cp1252_only_after_the_shared_path() -> None:
    """The doctor printed U+2192 to a cp1252 pipe and died on the failure it
    reported. A module under mcp_server/ or plugins/ may print such a literal
    only if it also calls ``use_utf8_output``."""
    offenders: dict[str, list[tuple[int, str]]] = {}
    for path in _py("mcp_server", "plugins"):
        tree = ast.parse(path.read_text("utf-8"))
        hits = _print_literals_outside("cp1252", tree)
        if hits and not _calls_shared_path(tree):
            offenders[str(path.relative_to(ROOT))] = hits
    assert not offenders, f"print() literals cp1252 cannot encode: {offenders}"


def test_the_literal_predicate_fires_outside_the_code_page_only() -> None:
    assert _print_literals_outside("cp1252", ast.parse("print('a → b')")) == [(1, "→")]
    assert not _print_literals_outside("cp1252", ast.parse("print('a — b')"))
    assert _calls_shared_path(ast.parse("def f():\n    use_utf8_output()\n"))
    assert not _calls_shared_path(ast.parse("def f():\n    print(1)\n"))


@pytest.mark.parametrize(
    ("path", "function"),
    [
        ("mcp_server/doctor.py", "run"),
        ("mcp_server/doctor_mcp.py", "run_mcp"),
    ],
)
def test_the_doctor_entry_points_set_utf8_before_anything_else(
    path: str, function: str
) -> None:
    tree = ast.parse((ROOT / path).read_text("utf-8"))
    entry = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == function
    )
    body = entry.body[1:] if ast.get_docstring(entry) else entry.body
    first = body[0]
    assert isinstance(first, ast.Expr) and isinstance(first.value, ast.Call)
    assert getattr(first.value.func, "id", None) == CALL


def _cp1252_env(tmp_path: Path) -> dict[str, str]:
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in {"DATABASE_URL", "PYTHONUTF8", "CORTEX_MEMORY_STORE_BACKEND"}
    }
    env.update(
        HOME=str(tmp_path),
        USERPROFILE=str(tmp_path),
        PYTHONIOENCODING="cp1252",
        CORTEX_MEMORY_STORE_BACKEND="postgresql",
    )
    return env


def _assert_arrow_reaches_the_pipe_as_utf8(done: subprocess.CompletedProcess) -> None:
    assert b"UnicodeEncodeError" not in done.stderr, done.stderr.decode(
        "utf-8", "backslashreplace"
    )
    assert "→" in done.stdout.decode("utf-8")


def test_the_doctor_reports_a_failure_on_a_cp1252_pipe(tmp_path: Path) -> None:
    """With the PostgreSQL backend and no DATABASE_URL a required check fails,
    so the doctor prints its fix hint behind U+2192, the character that raised
    ``UnicodeEncodeError`` before the doctor set its stdout to UTF-8."""
    done = subprocess.run(
        [sys.executable, "-m", "mcp_server.doctor"],
        capture_output=True,
        env=_cp1252_env(tmp_path),
        cwd=ROOT,
        timeout=120,
    )
    assert done.returncode == 1
    _assert_arrow_reaches_the_pipe_as_utf8(done)


def test_the_mcp_doctor_reports_a_failure_on_a_cp1252_pipe(tmp_path: Path) -> None:
    """``cortex-doctor mcp`` with one failing check, through the real entry."""
    script = (
        "import sys\n"
        "from mcp_server import doctor_mcp\n"
        "bad = doctor_mcp.McpCheck(name='x', ok=False, detail='d', fix='fix it')\n"
        "doctor_mcp.collect_mcp_report = lambda: doctor_mcp.McpReport(checks=[bad])\n"
        "sys.exit(doctor_mcp.run_mcp())\n"
    )
    done = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        env=_cp1252_env(tmp_path),
        cwd=ROOT,
        timeout=120,
    )
    assert done.returncode == 1
    _assert_arrow_reaches_the_pipe_as_utf8(done)
