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
import subprocess
import sys
from pathlib import Path

try:
    from ci_diff_lines import SOURCE_ROOT, changed_lines, changed_lines_ex  # noqa: F401
    from ci_diff_lines import string_cut_lines
except ModuleNotFoundError:  # imported as scripts.ci_mutation_diff
    from scripts.ci_diff_lines import (  # noqa: F401
        SOURCE_ROOT,
        changed_lines,
        changed_lines_ex,
        string_cut_lines,
    )

ROOT = Path(__file__).resolve().parent.parent
# source: scripts/mutation_equivalents.py reads this name; a rename breaks both.
SCOPE_ENV = "MUTATION_ONLY_PREFIXES"
# source: scripts/mutation_check.sh passes it to `mutmut run --max-children`.
MAX_CHILDREN_ENV = "MUTMUT_MAX_CHILDREN"
# source: mutmut 3.8.1 mutates a decorated function only when every decorator is
# one of these; any other decorator makes it emit no mutant at all.
MUTABLE_DECORATORS = frozenset({"staticmethod", "classmethod"})
# source: tests_py layout; these directories test scripts, benchmarks or the
# running system, not the unit behaviour of a module.
NOT_UNIT_TESTS = frozenset({"scripts", "integration", "benchmarks"})


# source: mutmut 3.8.1 `results` statuses besides killed and survived, the
# ones where no test showed the mutant to be wrong.
NOT_KILLED = frozenset({"no tests", "timeout", "suspicious", "not checked", "segfault"})


def scope_prefixes(environ=os.environ) -> list[str]:
    """Mutant-name prefixes in scope; empty means the whole run is in scope."""
    return [p for p in environ.get(SCOPE_ENV, "").splitlines() if p]


def in_scope(name: str, prefixes: list[str]) -> bool:
    return not prefixes or any(name.startswith(p) for p in prefixes)


def module_name(path: str) -> str:
    parts = path.removesuffix(".py").split("/")
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def _skipped_by_mutmut(node: ast.AST) -> bool:
    return any(
        not (isinstance(d, ast.Name) and d.id in MUTABLE_DECORATORS)
        for d in node.decorator_list
    )


_FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)


def _span(node: ast.AST, following: int) -> tuple[int, int]:
    """A function owns its decorators and the blank lines that trail it."""
    first = min([node.lineno, *(d.lineno for d in node.decorator_list)])
    return first, max(node.end_lineno, following - 1)


def _next_start(siblings: list[ast.stmt], index: int, total: int) -> int:
    if index + 1 < len(siblings):
        nxt = siblings[index + 1]
        decorators = getattr(nxt, "decorator_list", [])
        return min([nxt.lineno, *(d.lineno for d in decorators)])
    return total + 1


def _members(tree: ast.Module, total: int):
    """(owner, node, first, last) for each top-level function and method."""
    for i, node in enumerate(tree.body):
        following = _next_start(tree.body, i, total)
        if isinstance(node, _FUNCTIONS):
            yield None, node, *_span(node, following)
        elif isinstance(node, ast.ClassDef):
            for j, item in enumerate(node.body):
                if isinstance(item, _FUNCTIONS):
                    # The last method stops where the class does, not at end of file.
                    after = (
                        _next_start(node.body, j, total)
                        if j + 1 < len(node.body)
                        else following
                    )
                    yield node.name, item, *_span(item, after)


def touched_prefixes(
    source: str,
    lines: set[int],
    module: str,
    cuts: set[tuple[int, int]] = frozenset(),
    skipped: list[str] | None = None,
) -> list[str]:
    """mutmut name prefixes of the top-level functions and methods holding `lines`.

    mutmut 3 names a function `<module>.x_<name>__mutmut_N` and a method
    `<module>.xǁ<Class>ǁ<name>__mutmut_N`; nested functions belong to their outer one.
    `cuts` are (anchor, indent) of indented definitions the diff removed: one nested
    deeper than the member holding the anchor is a nested function (the member is
    touched), one at the member's own indent is a whole method (nothing that survives
    is); a cut inside a multiline string touches the function holding the string.
    A function mutmut cannot mutate goes to `skipped` instead of the result.
    """
    tree = ast.parse(source)
    lines = lines | string_cut_lines(tree, cuts)
    members = list(_members(tree, len(source.splitlines())))
    found: list[str] = []
    for owner, node, first, last in members:
        nested = any(
            first <= a <= last and indent > node.col_offset for a, indent in cuts
        )
        if not nested and not any(first <= n <= last for n in lines):
            continue
        name = (
            f"{module}.x_{node.name}__mutmut_"
            if owner is None
            else f"{module}.xǁ{owner}ǁ{node.name}__mutmut_"
        )
        if _skipped_by_mutmut(node):
            if skipped is not None:
                skipped.append(name)
        else:
            found.append(name)
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


def plan(
    diff_text: str, root: Path = ROOT, notices: list[str] | None = None
) -> tuple[list[dict], list[str]]:
    """(mutation jobs, problems). A changed function with no test is a problem.

    `notices` collects the changed functions mutmut cannot mutate (see
    MUTABLE_DECORATORS): they are reported, not gated, because no test could kill a
    mutant that does not exist.
    """
    jobs, problems = [], []
    lines_by_path, cuts_by_path = changed_lines_ex(diff_text)
    for path in sorted(lines_by_path.keys() | cuts_by_path.keys()):
        lines = lines_by_path.get(path, set())
        file = root / path
        if not file.exists():
            continue
        module = module_name(path)
        skipped: list[str] = []
        prefixes = touched_prefixes(
            file.read_text(encoding="utf-8"),
            lines,
            module,
            cuts_by_path.get(path, set()),
            skipped,
        )
        if notices is not None:
            notices.extend(f"{path}: not mutable by mutmut: {n}" for n in skipped)
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
    """In-scope mutants no test killed: `mutmut results` lines in NOT_KILLED."""
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
            print(f"!!! mutant not killed: {name}", file=sys.stderr)
        return 1 if names else 0
    base_ref = os.environ.get("GITHUB_BASE_REF", "")
    if not base_ref:
        print(">>> mutation: not a pull request, skipped")
        return 0
    notices: list[str] = []
    jobs, problems = plan(base_diff(base_ref), notices=notices)
    for notice in notices:
        print(f"::warning::{notice}")
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
