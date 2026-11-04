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
# source: pyproject.toml [tool.mutmut] source_paths = ["mcp_server"].
SOURCE_ROOT = "mcp_server/"
# source: tests_py layout; these directories test scripts, benchmarks or the
# running system, not the unit behaviour of a module.
NOT_UNIT_TESTS = frozenset({"scripts", "integration", "benchmarks"})
_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def scope_prefixes(environ=os.environ) -> list[str]:
    """Mutant-name prefixes in scope; empty means the whole run is in scope."""
    return [p for p in environ.get(SCOPE_ENV, "").splitlines() if p]


def in_scope(name: str, prefixes: list[str]) -> bool:
    return not prefixes or any(name.startswith(p) for p in prefixes)


def changed_lines(diff_text: str) -> dict[str, set[int]]:
    """Lines added or touched per Python file under mcp_server, from `git diff -U0`."""
    result: dict[str, set[int]] = {}
    current = None
    for line in diff_text.splitlines():
        if line.startswith("+++ "):
            path = line[4:].removeprefix("b/")
            current = (
                path if path.startswith(SOURCE_ROOT) and path.endswith(".py") else None
            )
        elif current and (hunk := _HUNK.match(line)):
            start = int(hunk.group(1))
            count = 1 if hunk.group(2) is None else int(hunk.group(2))
            # A pure deletion (count 0) touches the function holding line `start`.
            result.setdefault(current, set()).update(
                range(start, start + max(count, 1))
            )
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

    def hit(node: ast.AST) -> bool:
        return any(node.lineno <= n <= node.end_lineno for n in lines)

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and hit(node):
            found.append(f"{module}.x_{node.name}__mutmut_")
        elif isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and hit(
                    item
                ):
                    found.append(f"{module}.xǁ{node.name}ǁ{item.name}__mutmut_")
    return found


def select_tests(module: str, tests_root: Path, base: Path = ROOT) -> list[str]:
    """Test files that import the module by its dotted path or from its package."""
    package, _, stem = module.rpartition(".")
    dotted = re.compile(rf"\b{re.escape(module)}\b")
    from_pkg = re.compile(
        rf"from {re.escape(package)} import[^\n]*\b{re.escape(stem)}\b"
    )
    chosen = []
    for test in sorted(tests_root.rglob("test_*.py")):
        if set(test.relative_to(tests_root).parts) & NOT_UNIT_TESTS:
            continue
        text = test.read_text(encoding="utf-8", errors="replace")
        if dotted.search(text) or from_pkg.search(text):
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
    env = {**os.environ, SCOPE_ENV: "\n".join(job["prefixes"]), "UV_NO_SYNC": "1"}
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


def base_diff(base_ref: str) -> str:
    """Diff of the PR against its base. The checkout is the merge commit, depth 1."""
    subprocess.run(
        ["git", "fetch", "--no-tags", "--depth=1", "origin", base_ref],
        cwd=ROOT,
        check=True,
    )
    out = subprocess.run(
        ["git", "diff", "-U0", "FETCH_HEAD", "HEAD", "--", SOURCE_ROOT],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return out.stdout


def main(argv: list[str]) -> int:
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
