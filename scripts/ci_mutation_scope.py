#!/usr/bin/env python3
"""Run only the mutants of the changed functions; tell an empty scope apart (ADR-1122).

`mutmut run` with no name runs every mutant of the file, and the gate used to judge
only the changed functions afterwards: #865 ran 262 mutants of one file for six hours
to judge a few. Passing `<prefix>*` per changed function to `mutmut run` runs only
those.

mutmut 3.8.1 asserts when no mutant matches the names it is given (a changed function
with nothing to mutate). `main` reads mutmut's own files after such a failed run: when
the stats run succeeded and the generated mutants hold none in scope, the scope is empty
and the gate has nothing to judge; anything else is a real failure.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# source: mutmut 3.8.1 stats.py save_stats(); written only after the stats run succeeds.
STATS_FILE = "mutmut-stats.json"
# source: mutmut 3.8.1 mutation/data.py SourceFileMutationData.meta_path.
META_SUFFIX = ".meta"
# source: mutmut 3.8.1 mutation/data.py, the key holding one entry per generated mutant.
MUTANTS_KEY = "exit_code_by_key"
# source: scripts/ci_mutation_diff.py SCOPE_ENV, the variable both scripts read.
SCOPE_ENV = "MUTATION_ONLY_PREFIXES"
# source: the CLI below, `--empty-scope <mutants dir>`.
EMPTY_SCOPE_ARGS = 2


def name_globs(prefixes: list[str]) -> list[str]:
    """The `mutmut run` arguments selecting every mutant of each changed function."""
    return [f"{prefix}*" for prefix in prefixes]


def in_scope_count(mutants_dir: Path, prefixes: list[str]) -> int | None:
    """Generated mutants in scope; None when mutmut did not get past its stats run."""
    if not (mutants_dir / STATS_FILE).is_file():
        return None
    count = 0
    for meta in mutants_dir.rglob(f"*{META_SUFFIX}"):
        names = json.loads(meta.read_text(encoding="utf-8"))[MUTANTS_KEY]
        count += sum(1 for name in names if name.startswith(tuple(prefixes)))
    return count


def main(argv: list[str]) -> int:
    prefixes = [p for p in os.environ.get(SCOPE_ENV, "").splitlines() if p]
    if argv[:1] == ["--globs"]:
        print("\n".join(name_globs(prefixes)))
        return 0
    if argv[:1] != ["--empty-scope"] or len(argv) != EMPTY_SCOPE_ARGS or not prefixes:
        print(
            "usage: MUTATION_ONLY_PREFIXES=... ci_mutation_scope.py "
            "--globs | --empty-scope <mutants dir>",
            file=sys.stderr,
        )
        return 2
    count = in_scope_count(Path(argv[1]), prefixes)
    if count == 0:
        print(">>> mutation: the changed functions hold no mutant; nothing to judge")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
