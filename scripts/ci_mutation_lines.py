#!/usr/bin/env python3
"""Keep only the mutants on the lines a pull request changed (ADR-1122).

mutmut names a mutant after its function, not its line. `mutation_check.sh` runs
every mutant of each changed function; this module tells which of them alter a line
the PR changed, by diffing the mutant against mutmut's unmutated copy of the function
(both indexed in `mutants/<path>.spans`) and placing the difference on the source.
A mutant on a line the PR did not touch was there before the PR, and judging it here
made a one-line change pay for the whole function (#865, #878; owner, 2026-11-06).

`MUTATION_ONLY_LINES` is `<path>=<line>,<line>,...`, set by `ci_mutation_diff.run_job`.
Without it every mutant is kept. A mutant whose lines cannot be placed stops the gate:
guessing would let a change escape or fail it for nothing.
"""

from __future__ import annotations

import ast
import difflib
import json
import os
import re
import sys
from pathlib import Path

# source: scripts/ci_mutation_diff.run_job sets it; mutation_check.sh forwards it.
LINES_ENV = "MUTATION_ONLY_LINES"
# source: mutmut 3.8.1 mutation/data.py MutantLineSpans, the version it writes.
SPANS_VERSION = 1
# source: mutmut 3.8.1 trampoline names (`x_<f>`, `xǁ<Class>ǁ<m>`, `__mutmut_<n>`).
MUTANT_SEP = "__mutmut_"
METHOD_SEP = "ǁ"
_DEF = re.compile(r"^(\s*(?:async\s+)?def\s+)[^\s(]+")


class LineMapError(RuntimeError):
    """mutmut's files do not let the mutant be placed on the source."""


class UnknownMutantError(LookupError):
    """mutmut generated no mutant of that name."""


def parse_scope(value: str) -> tuple[str, frozenset[int]] | None:
    """(path, lines) from `<path>=<line>,...`; None when the variable is empty."""
    if not value:
        return None
    path, sep, numbers = value.partition("=")
    if not sep or not path:
        raise LineMapError(f"{LINES_ENV} is not <path>=<lines>: {value!r}")
    return path, frozenset(int(n) for n in numbers.split(",") if n)


def _function_node(tree: ast.Module, key: str) -> ast.AST:
    """The source definition a mutant key (`x_f`, `xǁCǁm`) names."""
    owner, name = None, key.removeprefix("x_")
    if key.startswith("x" + METHOD_SEP):
        _, owner, name = key.split(METHOD_SEP)
    body = tree.body
    if owner is not None:
        cls = next((n for n in body if getattr(n, "name", None) == owner), None)
        body = getattr(cls, "body", [])
    for node in body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == name:
                return node
    raise LineMapError(f"no definition for {key} in the source")


def _generated(lines: list[str], span: list[int]) -> list[str]:
    """A generated function from its `def` line, its name made neutral."""
    segment = lines[span[0] : span[1]]
    start = next((i for i, line in enumerate(segment) if _DEF.match(line)), None)
    if start is None:
        raise LineMapError(f"no def line in span {span}")
    body = segment[start:]
    return [_DEF.sub(r"\1f", body[0], count=1), *body[1:]]


def mutated_lines(root: Path, path: str, mutant: str) -> set[int]:
    """Source lines (1-based) that `mutant` alters in `path`."""
    spans_file = root / "mutants" / f"{path}.spans"
    index = json.loads(spans_file.read_text(encoding="utf-8"))
    if index.get("version") != SPANS_VERSION:
        raise LineMapError(f"{spans_file}: spans version {index.get('version')}")
    key = mutant.rsplit(".", 1)[-1]
    function = key.rsplit(MUTANT_SEP, 1)[0]
    generated = (root / "mutants" / path).read_text(encoding="utf-8").splitlines()
    spans = index["spans"]
    if key not in spans:
        raise UnknownMutantError(key)
    if f"{function}{MUTANT_SEP}orig" not in spans:
        raise LineMapError(f"{spans_file}: no unmutated copy of {function}")
    orig = _generated(generated, spans[f"{function}{MUTANT_SEP}orig"])
    changed = _generated(generated, spans[key])
    source = (root / path).read_text(encoding="utf-8")
    node = _function_node(ast.parse(source), function)
    own = source.splitlines()[node.lineno - 1 : node.end_lineno]
    if [s.strip() for s in orig[1:]] != [s.strip() for s in own[1:]]:
        raise LineMapError(f"{key}: mutmut's copy of {function} differs from source")
    found: set[int] = set()
    matcher = difflib.SequenceMatcher(None, orig, changed, autojunk=False)
    for tag, i1, i2, _, _ in matcher.get_opcodes():
        if tag != "equal":
            span = range(i1, i2) if i2 > i1 else {max(i1 - 1, 0), i1}
            found.update(node.lineno + i for i in span if i < len(orig))
    return found


def keeps(mutant: str, root: Path, environ=os.environ) -> bool:
    """Whether the gate judges `mutant`: no line scope, or it alters a changed line.

    A name mutmut did not generate (a registry entry whose mutant is gone) is kept,
    so the registry check still reports it as stale.
    """
    scope = parse_scope(environ.get(LINES_ENV, ""))
    if scope is None:
        return True
    path, lines = scope
    try:
        return bool(mutated_lines(root, path, mutant) & lines)
    except UnknownMutantError:
        return True


def job_lines(lines: set[int], cuts) -> list[int]:
    """The lines a job judges: changed ones, and for a cut its anchor and the next."""
    return sorted(lines | {anchor + i for anchor, _ in cuts for i in (0, 1)})


def scope_value(path: str, lines: list[int]) -> str:
    """The `MUTATION_ONLY_LINES` value for one mutated file."""
    return f"{path}={','.join(map(str, lines))}"


def judged(names: list[str], root: Path, environ=os.environ) -> list[str]:
    """`names` on changed lines; reports how many it leaves out, on stderr."""
    kept = [name for name in names if keeps(name, root, environ)]
    if len(kept) < len(names):
        print(
            f">>> {len(names) - len(kept)} survivor(s) on lines this change did not "
            "touch: not judged here (ADR-1122)",
            file=sys.stderr,
        )
    return kept
