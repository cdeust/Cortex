"""Operand grammar prevents shell syntax from becoming invented file cues."""

import pytest

from mcp_server.hooks.shell_read_paths import shell_read_paths


@pytest.fixture
def files(tmp_path):
    for name in ("a.py", "b.py", "space name.py", "-dash.py"):
        (tmp_path / name).write_text("hello")
    return tmp_path


@pytest.mark.parametrize(
    "command,names",
    [
        ("cat a.py b.py", ["a.py", "b.py"]),
        ("cat -n -- -dash.py", ["-dash.py"]),
        ('head -n 20 "space name.py"', ["space name.py"]),
        ("tail -n+10 a.py", ["a.py"]),
        ("head --lines=5 a.py", ["a.py"]),
        ("sed -n '1,20p' a.py", ["a.py"]),
        ("rg -n hello a.py b.py", ["a.py", "b.py"]),
        ("rg -e hello -- a.py", ["a.py"]),
        ("rg --regexp=hello -g '*.py' a.py", ["a.py"]),
        ("cat a.py ./a.py", ["a.py"]),
    ],
)
def test_explicit_files(command, names, files):
    assert shell_read_paths(command, str(files)) == [
        str(files / name) for name in names
    ]


@pytest.mark.parametrize(
    "command",
    [
        "cat $(echo a.py)",
        "cat `echo a.py`",
        "cat $FILE",
        "cat *.py",
        "cat a.py; cat b.py",
        "cat a.py && cat b.py",
        "cat a.py | head",
        "cat < a.py",
        "cat a.py > b.py",
        "cat a.py\ncat b.py",
        "sed -i '1p' a.py",
        "sed -n '1w b.py' a.py",
        "sed -f a.py b.py",
        "rg --pre a.py hello b.py",
        "rg --files .",
        "cat -z a.py",
        "python a.py",
        "custom/cat a.py",
        "./cat a.py",
        "cat 'a.py",
        "cat .",
        "cat missing.py",
    ],
)
def test_ambiguous_or_nonread_commands_do_not_guess(command, files):
    assert shell_read_paths(command, str(files)) == []


def test_rg_pattern_is_not_mistaken_for_a_file_or_option(files):
    assert shell_read_paths("rg -g -e a.py b.py", str(files)) == [str(files / "b.py")]
    assert shell_read_paths("rg -- a.py -e", str(files)) == []
