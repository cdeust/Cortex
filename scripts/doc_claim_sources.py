"""Canonical truth-readers for scripts/check_doc_claims.py.

source: ADR-0730"""

from __future__ import annotations

import ast
import re
from collections.abc import Callable

ReadFn = Callable[[str], str]

# source: ADR-0730
_MARKER_SPLIT_PARTS = 2


class ClaimError(Exception):
    """A canonical source could not be read — the gate cannot run blind."""


def canonical_tool_counts(read_fn: ReadFn) -> tuple[int, int]:
    """(standalone, total) from the mcp-tools.md header, cross-checked.

    The header sentence is the single place the catalogue states the counts;
    the pinned test name in tests_py/test_main.py carries the registry-derived
    standalone number, so the two disagreeing means the catalogue drifted from
    the server itself.
    """
    header = read_fn("docs/mcp-tools.md")
    match = re.search(
        r"(\d+)\s+standalone tools register unconditionally;"
        r"\s*(\d+)\s+more[^(]*\((\d+)\s+total",
        header,
    )
    if not match:
        raise ClaimError("docs/mcp-tools.md: standalone/total tool sentence not found")
    standalone, extra, total = (int(g) for g in match.groups())
    if standalone + extra != total:
        raise ClaimError(f"docs/mcp-tools.md: {standalone} + {extra} != {total}")

    pinned = re.search(
        r"test_standalone_baseline_is_(\d+)_tools", read_fn("tests_py/test_main.py")
    )
    if not pinned:
        raise ClaimError("tests_py/test_main.py: pinned tool-count test not found")
    if int(pinned.group(1)) != standalone:
        raise ClaimError(
            f"docs/mcp-tools.md says {standalone} standalone tools, but the pinned "
            f"registry test says {pinned.group(1)}"
        )
    return standalone, total


def canonical_reference_count(read_fn: ReadFn) -> int:
    """Entries counted in the bibliography, which declares itself canonical."""
    body = read_fn("docs/papers/bibliography.md").split("## References", 1)
    if len(body) != _MARKER_SPLIT_PARTS:
        raise ClaimError(
            "docs/papers/bibliography.md: '## References' section not found"
        )
    entries = [
        line
        for line in body[1].splitlines()
        if line.strip() and not line.startswith(("#", "---"))
    ]
    if not entries:
        raise ClaimError("docs/papers/bibliography.md: no reference entries found")
    return len(entries)


def canonical_hook_count(read_fn: ReadFn) -> int:
    """How many lifecycle hooks the docs may claim.

    The allowlist in `mcp_server/hooks/entry.py` is what both plugin manifests
    wire and what the console script accepts, so it is the only number a doc
    can mean. It is read as TEXT, like every other canonical source here, and
    never imported: the Lint job that runs this gate installs ruff and nothing
    else (`requirements/lint.txt`, ci.yml), so `import mcp_server` raises
    ModuleNotFoundError there and takes the whole pipeline down with it.
    A late import does not help, because this is called unconditionally.
    """
    tree = ast.parse(read_fn("mcp_server/hooks/entry.py"))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(t, ast.Name) and t.id == "HOOK_MODULES" for t in node.targets
        ):
            continue
        value = node.value
        # `frozenset({...})`: unwrap the call and evaluate its one argument.
        if isinstance(value, ast.Call) and value.args:
            value = value.args[0]
        try:
            return len(ast.literal_eval(value))
        except (ValueError, TypeError) as exc:
            raise ClaimError(f"HOOK_MODULES is not a literal set: {exc}") from exc
    raise ClaimError("mcp_server/hooks/entry.py declares no HOOK_MODULES")


def canonical_mechanism_count(read_fn: ReadFn) -> int:
    """The mechanism count declared in the bibliography header.

    Mechanisms are not machine-countable (they are implementations spread over
    core modules), so one file declares the number and every other file must
    agree with it. Changing the count is a one-line edit here plus whatever the
    gate then reports as stale.
    """
    pattern = re.compile(
        r"(\d+)\s+(?:neuroscience[- ]grounded|neuroscience|biological|brain)?"
        r"\s*mechanisms\b"
    )
    match = pattern.search(read_fn("docs/papers/bibliography.md"))
    if not match:
        raise ClaimError("docs/papers/bibliography.md: no mechanism count declared")
    return int(match.group(1))


def canonical_version(read_fn: ReadFn) -> str:
    match = re.search(
        r'^version\s*=\s*"([^"]+)"', read_fn("pyproject.toml"), re.MULTILINE
    )
    if not match:
        raise ClaimError("pyproject.toml: [project].version not found")
    return match.group(1)
