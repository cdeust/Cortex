#!/usr/bin/env python3
"""Mutation testing scoped to the functions a pull request changes (ADR-1122).

mutmut mutates whole files, and a file may carry survivors older than the PR
(the whole of ast_extractors.py fails today). Gating on the file would turn
every PR red for code it did not touch. This module narrows the gate to the
functions whose lines the PR changed: the diff-based mutation testing that
Google reports at scale (Petrovic and Ivankovic, ICSE-SEIP 2018,
doi 10.1145/3183519.3183521; Petrovic et al., arXiv 2102.11378).

`run` plans from `git diff` and calls scripts/mutation_check.sh once per
changed file with MUTATION_ONLY_PREFIXES set; mutation_equivalents.py reads
that variable and ignores survivors and registry entries outside it.
"""

from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# source: scripts/mutation_equivalents.py reads this name; a rename breaks both.
SCOPE_ENV = "MUTATION_ONLY_PREFIXES"
# source: scripts/mutation_check.sh passes it to `mutmut run --max-children`.
MAX_CHILDREN_ENV = "MUTMUT_MAX_CHILDREN"
# source: pyproject.toml [tool.mutmut] source_paths = ["mcp_server"].
SOURCE_ROOT = "mcp_server/"
# source: tests_py layout; these directories test scripts, benchmarks or the
# running system, not the unit behaviour of a module.
NOT_UNIT_TESTS = frozenset({"scripts", "integration", "benchmarks"})
_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


# source: mutmut 3.8.1 `results` statuses besides killed and survived.
NOT_KILLED = frozenset({"no tests", "timeout", "suspicious"})


def scope_prefixes(environ=os.environ) -> list[str]:
    """Mutant-name prefixes in scope; empty means the whole run is in scope."""
    return [p for p in environ.get(SCOPE_ENV, "").splitlines() if p]


def in_scope(name: str, prefixes: list[str]) -> bool:
    return not prefixes or any(name.startswith(p) for p in prefixes)


_DEFINITION = re.compile(r"-(?:async\s+def\b|def\b|class\b|@)")


def _removes_a_definition(removed: list[str]) -> bool:
    """True when a deleted block starts with a top-level def, class or decorator."""
    first = next((r for r in removed if r[1:].strip()), "")
    return bool(_DEFINITION.match(first)) and not first[1:].startswith(" ")


def changed_lines(diff_text: str) -> dict[str, set[int]]:
    """Lines added or touched per Python file under mcp_server, from `git diff -U0`.

    A pure deletion anchors on the line before the cut. When the deleted block is a
    whole top-level definition nothing that survives was changed and the hunk is
    dropped; otherwise the anchor and the next line count as touched, and
    `touched_prefixes` lets a function own the blank lines that trail it.
    """
    result: dict[str, set[int]] = {}
    current = None
    pending: tuple[int, int] | None = None
    removed: list[str] = []

    def close() -> None:
        nonlocal pending, removed
        if pending and current and not _removes_a_definition(removed):
            start, count = pending
            result.setdefault(current, set()).update(
                range(start, start + max(count, 2 if count == 0 else 1))
            )
        pending, removed = None, []

    for line in diff_text.splitlines():
        if line.startswith("+++ "):
            close()
            path = line[4:].removeprefix("b/")
            current = (
                path if path.startswith(SOURCE_ROOT) and path.endswith(".py") else None
            )
        elif current and (hunk := _HUNK.match(line)):
            close()
            count = 1 if hunk.group(2) is None else int(hunk.group(2))
            pending = (int(hunk.group(1)), count)
        elif pending and line.startswith("-") and pending[1] == 0:
            removed.append(line)
    close()
    return result


def module_name(path: str) -> str:
    parts = path.removesuffix(".py").split("/")
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def touched_prefixes(source: str, lines: set[int], module: str) -> list[str]:
    """mutmut name prefixes of the top-level functions and methods holding `lines`.

    mutmut 3 names a function `<module>.x_<name>__mutmut_N` and a method
    `<module>.xǁ<Class>ǁ<name>__mutmut_N`; nested functions belong to their outer one.
    """
    tree = ast.parse(source)
    found: list[str] = []
    total = len(source.splitlines())

    def hit(node: ast.AST, following: int) -> bool:
        # A function owns its decorators and the blank lines that trail it.
        first = min([node.lineno, *(d.lineno for d in node.decorator_list)])
        last = max(node.end_lineno, following - 1)
        return any(first <= n <= last for n in lines)

    def next_start(siblings: list[ast.stmt], index: int) -> int:
        if index + 1 < len(siblings):
            nxt = siblings[index + 1]
            decorators = getattr(nxt, "decorator_list", [])
            return min([nxt.lineno, *(d.lineno for d in decorators)])
        return total + 1

    for i, node in enumerate(tree.body):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if hit(node, next_start(tree.body, i)):
                found.append(f"{module}.x_{node.name}__mutmut_")
        elif isinstance(node, ast.ClassDef):
            for j, item in enumerate(node.body):
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and hit(
                    item, next_start(node.body, j)
                ):
                    found.append(f"{module}.xǁ{node.name}ǁ{item.name}__mutmut_")
    return found


def _imports(tree: ast.AST) -> set[str]:
    """Dotted names a test imports: `import a.b`, `from a import b` -> a, a.b."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            names.add(node.module)
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
    return names


def select_tests(module: str, tests_root: Path, base: Path = ROOT) -> list[str]:
    """Test files that import the module by its dotted path or from its package.

    Imports are read with `ast`, so a parenthesized multiline
    `from pkg import (a, b)` counts the same as a one line import.
    """
    chosen = []
    for test in sorted(tests_root.rglob("test_*.py")):
        if set(test.relative_to(tests_root).parts) & NOT_UNIT_TESTS:
            continue
        try:
            tree = ast.parse(test.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        if module in _imports(tree):
            chosen.append(test.relative_to(base).as_posix())
    return chosen


def plan(diff_text: str, root: Path = ROOT) -> tuple[list[dict], list[str]]:
    """(mutation jobs, problems). A changed function with no test is a problem."""
    jobs, problems = [], []
    for path, lines in sorted(changed_lines(diff_text).items()):
        file = root / path
        if not file.exists():
            continue
        module = module_name(path)
        prefixes = touched_prefixes(file.read_text(encoding="utf-8"), lines, module)
        if not prefixes:
            continue
        tests = select_tests(module, root / "tests_py", root)
        if not tests:
            problems.append(f"{path}: functions changed, no test file imports {module}")
            continue
        jobs.append({"file": path, "tests": tests, "prefixes": prefixes})
    return jobs, problems


def run_job(job: dict) -> int:
    env = {
        **os.environ,
        SCOPE_ENV: "\n".join(job["prefixes"]),
        "UV_NO_SYNC": "1",
        # source: tests_py/conftest.py _clean_all_tables() empties the one shared
        # database before every test; concurrent mutmut workers would erase each
        # other's rows and count the failures as killed mutants.
        MAX_CHILDREN_ENV: "1",
    }
    cmd = [
        "bash",
        "scripts/mutation_check.sh",
        " ".join(job["tests"]),
        "--",
        job["file"],
    ]
    print(
        f">>> mutation: {job['file']} ({len(job['prefixes'])} function(s))", flush=True
    )
    return subprocess.run(cmd, cwd=ROOT, env=env).returncode  # noqa: PLW1510


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout


def base_diff(base_ref: str) -> str:
    """Diff from the merge base of the base branch and HEAD, the `A...B` perimeter.

    The merge base does not move when the base branch advances, and it is right for
    both checkouts that run this step: the pull request merge commit and the PR head.
    """
    shallow = _git("rev-parse", "--is-shallow-repository").strip() == "true"
    fetch = ["fetch", "--no-tags", *(["--unshallow"] if shallow else []), "origin"]
    _git(*fetch, base_ref)
    return _git("diff", "-U0", "FETCH_HEAD...HEAD", "--", SOURCE_ROOT)


def untested(results: str, prefixes: list[str]) -> list[str]:
    """In-scope mutants no test reached: `mutmut results` lines `name: no tests`."""
    found = []
    for line in results.splitlines():
        name, _, status = line.strip().partition(":")
        if status.strip() in NOT_KILLED and in_scope(name, prefixes):
            found.append(name)
    return found


def main(argv: list[str]) -> int:
    if argv[:1] == ["--untested"]:
        prefixes = scope_prefixes()
        names = untested(sys.stdin.read(), prefixes) if prefixes else []
        for name in names:
            print(f"!!! mutant not killed (no test, timeout): {name}", file=sys.stderr)
        return 1 if names else 0
    base_ref = os.environ.get("GITHUB_BASE_REF", "")
    if not base_ref:
        print(">>> mutation: not a pull request, skipped")
        return 0
    jobs, problems = plan(base_diff(base_ref))
    failed = [job["file"] for job in jobs if run_job(job) != 0]
    for problem in problems:
        print(f"!!! {problem}", file=sys.stderr)
    for path in failed:
        print(
            f"!!! surviving mutants in the changed functions of {path}", file=sys.stderr
        )
    print(
        f">>> mutation: {len(jobs)} file(s), {len(failed)} failed, "
        f"{len(problems)} untested"
    )
    return 1 if failed or problems else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
