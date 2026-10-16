"""Mutation check of the SQLite tie-group fill (ADR-1109).

Usage: python scripts/recall_fill_mutants.py <out.txt>

Each mutant is one textual edit of ``mcp_server`` applied to a scratch copy
of the package and its tests; the property and tie-cut tests then run there
(from the copy, so the mutated package is the one imported). A mutant is
killed when at least one test fails. Mutants marked ``equivalent`` cannot
change any result (the reason is given) and are expected to survive.

source: ADR-1109
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INFRA = "mcp_server/infrastructure/"
TESTS = [
    "tests_py/infrastructure/test_sqlite_recall_fill_property.py",
    "tests_py/infrastructure/test_sqlite_recall_tie_cut.py",
]
FILL = INFRA + "sqlite_store_recall_fill.py"
GROUPS = INFRA + "sqlite_store_recall_groups.py"
# Each entry: name, file, the exact text replaced, its replacement, and the
# reason a mutant cannot change any result (empty when it can).
MUTANTS = [
    (
        "boost after the trust factor",
        FILL,
        "    score = base + adj.boost if agent else base\n"
        "    return score if trusted is not False else score * adj.untrusted_factor",
        "    score = base if trusted is not False else base * adj.untrusted_factor\n"
        "    return score + adj.boost if agent else score",
        "",
    ),
    (
        "seek misses NULL agents (= instead of IS)",
        FILL,
        "AND m.agent_context IS json_extract",
        "AND m.agent_context = json_extract",
        "",
    ),
    (
        "group credit starts one position late",
        "mcp_server/shared/tie_groups.py",
        "first = k + start + 1",
        "first = k + start + 2",
        "",
    ),
    (
        "one-row credit one position late",
        "mcp_server/shared/tie_groups.py",
        "            weight / (k + start + 1)\n",
        "            weight / (k + start + 2)\n",
        "",
    ),
    (
        "superseded rows kept in a column group",
        INFRA + "sqlite_store_recall_signals.py",
        '"m.superseded_by_id IS NULL", ',
        "",
        "",
    ),
    (
        "rows scored row by row not excluded",
        FILL,
        'where = ([*conds, f"m.id NOT {_IN_JSON}"], [*params, exclude_json])',
        "where = (conds, params)",
        "",
    ),
    (
        "fill oldest first",
        FILL,
        "ORDER BY m.created_at DESC, m.id DESC LIMIT ?) ",
        "ORDER BY m.created_at ASC, m.id ASC LIMIT ?) ",
        "",
    ),
    (
        "inclusion-exclusion sign flipped",
        GROUPS,
        "mask, sign = mask | ob, -sign",
        "mask, sign = mask | ob, sign",
        "",
    ),
    (
        "seek keeps one row fewer",
        FILL,
        "(json.dumps(pairs), *params, top, top)",
        "(json.dumps(pairs), *params, top - 1, top)",
        "",
    ),
    (
        "pair trust inverted",
        FILL,
        "else origin in self.trusted,",
        "else origin not in self.trusted,",
        "",
    ),
    (
        "pair agent match inverted",
        FILL,
        "None if not self.agent_topic else agent == self.agent_topic,",
        "None if not self.agent_topic else agent != self.agent_topic,",
        "",
    ),
    (
        "second group's pass keeps the rows shared with the first",
        GROUPS,
        'where.append(f"NOT COALESCE({test}, 0)")',
        'where.append(f"NOT COALESCE({test}, 0) OR 1")',
        "",
    ),
    (
        "shared rows dropped from totals without the earlier group",
        GROUPS,
        "counts[inside] = shared + mine",
        "counts[inside] = mine if earlier not in inside else shared",
        "",
    ),
    (
        "shared rows read without the group itself",
        GROUPS,
        "shared = theirs.get(pair, {}).get(rest | me, 0)",
        "shared = theirs.get(pair, {}).get(rest, 0)",
        "",
    ),
    (
        "pairs only in an earlier group dropped",
        GROUPS,
        "{p for p, c in theirs.items() if c.get(me, 0)}",
        "{p for p, c in theirs.items() if 0}",
        "",
    ),
    (
        "member test on the counted group's own column",
        GROUPS,
        'return f"m.{h.column} = ?", (h.params[0],)',
        'return f"m.{g.column} = ?", (h.params[0],)',
        "",
    ),
    (
        "empty pairs seeked too",
        FILL,
        "if class_count(anchor, counts, inside, outside) > 0:",
        "if class_count(anchor, counts, inside, outside) >= 0:",
        "a pair without class rows returns no row from its seek",
    ),
]


def run_mutant(scratch: Path, rel: str, old: str, new: str) -> str:
    """Apply one edit to a fresh copy and return the pytest summary line."""
    for tree in ("mcp_server", "tests_py", "scripts"):
        shutil.rmtree(scratch / tree, ignore_errors=True)
        shutil.copytree(ROOT / tree, scratch / tree)
    for name in ("pyproject.toml", "uv.lock"):
        shutil.copy2(ROOT / name, scratch / name)
    target = scratch / rel
    text = target.read_text()
    if text.count(old) != 1:
        raise SystemExit(f"mutant text not found exactly once in {rel}: {old!r}")
    target.write_text(text.replace(old, new))
    env = {**os.environ, "PYTHONPATH": str(scratch)}
    proc = subprocess.run(  # noqa: S603 — fixed argv, this repository's own interpreter and tests
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *TESTS],
        cwd=scratch,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    lines = [
        ln for ln in proc.stdout.splitlines() if re.search(r" (passed|failed) in ", ln)
    ]
    if not lines:
        raise SystemExit(
            f"pytest did not run for {rel}:\n{proc.stdout[-800:]}{proc.stderr[-800:]}"
        )
    return lines[-1]


def main() -> int:
    out = Path(sys.argv[1])
    report = []
    with tempfile.TemporaryDirectory() as tmp:
        for name, rel, old, new, equivalent in MUTANTS:
            summary = run_mutant(Path(tmp), rel, old, new)
            killed = "failed" in summary
            verdict = (
                "killed" if killed else ("equivalent" if equivalent else "SURVIVED")
            )
            report.append(
                f"{verdict:10s} | {name} | {summary}"
                + (f" | {equivalent}" if equivalent else "")
            )
    out.write_text("\n".join(report) + "\n")
    print("\n".join(report))
    survived = [r for r in report if r.startswith("SURVIVED")]
    return 1 if survived else 0


if __name__ == "__main__":
    raise SystemExit(main())
