#!/usr/bin/env python3
"""Re-verify mutmut "survived" mutants against the FULL test selection.

mutmut 3.x attributes each mutant to only the test(s) its coverage-tracing
trampoline recorded as calling the mutated function during the one-time
baseline stats pass (`mutants/mutmut-stats.json`,
`tests_by_mangled_function_name`). A module that builds a dispatch table
**once, eagerly, at import time** — e.g. `ast_parser._EXTRACTORS = {...,
**build_extra_extractors()}` — is invisible to that attribution for every
test after the first: later tests exercise the already-built, cached
closures without ever re-invoking `build_extra_extractors`/`_make_extractor`,
so mutmut re-runs the mutant against only the first (often irrelevant)
test and reports "survived" even though the full suite kills it.

This module closes that gap generically — for ANY source file, not just
one hand-identified case — by re-running every mutant mutmut reports
"survived" against the FULL declared test selection (the same tests a
human would use to reproduce the bug by hand) before trusting the
verdict. A mutant recovered this way is reported as such, never silently
reclassified: coding-standards.md issue #269 acceptance criterion 2
requires the false-survivor cause stay visible to the reader, not just
absorbed.

Pure decision logic (parse_survivors, format_report,
any_genuine_survivors) takes no I/O; only recheck_survivor's `runner`
touches the filesystem/process table, and it is injected so tests can
substitute a fake for the real pytest invocation.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

_SURVIVED_SUFFIX = ": survived"

# source: structural — <mutants_dir> + at least one <test_path>.
_MIN_ARGC = 2


def parse_survivors(mutmut_results_output: str) -> list[str]:
    """Extract mutant names `mutmut results` marked "survived".

    Precondition: `mutmut_results_output` is the text `mutmut results`
    (or `mutmut results --all`) printed to stdout, one `<name>: <status>`
    line per mutant (leading whitespace allowed, per mutmut's own
    `print(f"    {k}: {status}")`).
    Postcondition: returns every `<name>` whose status is exactly
    "survived", in the order encountered; a name is never returned twice
    even if the input repeats a line.
    """
    survivors: list[str] = []
    for line in mutmut_results_output.splitlines():
        stripped = line.strip()
        if not stripped.endswith(_SURVIVED_SUFFIX):
            continue
        name = stripped[: -len(_SURVIVED_SUFFIX)]
        if name and name not in survivors:
            survivors.append(name)
    return survivors


@dataclass(frozen=True)
class RecheckOutcome:
    """The full-selection verdict for one mutmut-reported survivor."""

    mutant_name: str
    genuinely_survived: bool
    exit_code: int


# Runs a command in `cwd` with `env` and returns the completed process;
# injected so tests never spawn a real pytest subprocess.
Runner = Callable[[list[str], dict[str, str], Path], "subprocess.CompletedProcess[str]"]


def default_runner(
    cmd: list[str], env: dict[str, str], cwd: Path
) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(cmd, env=env, cwd=cwd, capture_output=True, text=True)  # noqa: PLW1510, S603 — exit code is read by the caller, not raised; cmd is [sys.executable, "-m", "pytest", "-q", *full_test_selection], test paths from this repo's own suite, never external input


def recheck_survivor(
    mutant_name: str,
    full_test_selection: Sequence[str],
    *,
    mutants_dir: Path,
    base_env: dict[str, str],
    runner: Runner = default_runner,
) -> RecheckOutcome:
    """Re-run one mutmut-reported survivor against the full test selection.

    Precondition: `mutant_name` is a mutmut mutant identifier already
    generated under `mutants_dir` by a prior `mutmut run` (dotted module
    path + mangled function key, e.g.
    `mcp_server.core.ast_extractor_registry.x__make_extractor__mutmut_1`);
    `full_test_selection` is non-empty.
    Postcondition: `genuinely_survived` is True iff every test in
    `full_test_selection` passed with this mutant active (pytest exit 0)
    — i.e. no test in the FULL selection pins this mutant's behavior.
    False means the full selection kills it; mutmut's narrower per-mutant
    attribution was a false survivor, not a real test gap.
    """
    env = dict(base_env)
    env["MUTANT_UNDER_TEST"] = mutant_name
    cmd = [sys.executable, "-m", "pytest", "-q", *full_test_selection]
    result = runner(cmd, env, mutants_dir)
    return RecheckOutcome(
        mutant_name=mutant_name,
        genuinely_survived=result.returncode == 0,
        exit_code=result.returncode,
    )


def recheck_all_survivors(
    survivors: Sequence[str],
    full_test_selection: Sequence[str],
    *,
    mutants_dir: Path,
    base_env: dict[str, str],
    runner: Runner = default_runner,
) -> list[RecheckOutcome]:
    """Recheck every reported survivor; empty input yields an empty result.

    Precondition: `full_test_selection` is non-empty whenever `survivors`
    is non-empty (there is nothing meaningful to re-verify against zero
    tests).
    """
    if survivors and not full_test_selection:
        raise ValueError("full_test_selection must be non-empty to recheck survivors")
    return [
        recheck_survivor(
            name,
            full_test_selection,
            mutants_dir=mutants_dir,
            base_env=base_env,
            runner=runner,
        )
        for name in survivors
    ]


def any_genuine_survivors(outcomes: Sequence[RecheckOutcome]) -> bool:
    return any(outcome.genuinely_survived for outcome in outcomes)


def format_report(outcomes: Sequence[RecheckOutcome]) -> str:
    """Render the human-readable recheck report.

    Postcondition: a recovered (false-survivor) mutant is always listed
    under its own labeled section, distinct from a genuine survivor —
    the false-survivor cause must stay visible to the reader rather than
    being silently absorbed into a plain "killed" count (issue #269
    acceptance criterion 2).
    """
    if not outcomes:
        return "  none — 0 mutmut-reported survivors to recheck"

    recovered = [o for o in outcomes if not o.genuinely_survived]
    genuine = [o for o in outcomes if o.genuinely_survived]

    lines: list[str] = []
    if recovered:
        lines.append(
            f">>> {len(recovered)} mutmut-reported survivor(s) RECOVERED: killed by "
            "the full test selection, invisible to mutmut's per-mutant test "
            "attribution (eager module-level dispatch table — see issue #269):"
        )
        lines += [f"    {o.mutant_name} (pytest exit {o.exit_code})" for o in recovered]
    if genuine:
        lines.append(
            f">>> {len(genuine)} GENUINE surviving mutant(s) — a real test gap:"
        )
        lines += [f"    {o.mutant_name}" for o in genuine]
    else:
        lines.append(">>> 0 genuine survivors after full-selection reverification 🎉")
    return "\n".join(lines)


def _main(argv: list[str], *, runner: Runner = default_runner) -> int:
    """CLI entry point.

    Precondition: `argv` is `[mutants_dir, test_path, ...]`; stdin carries
    `mutmut results` output. `runner` is injected (defaulting to the real
    subprocess runner) so tests can exercise the full survivors-present
    path without spawning pytest.
    Postcondition: returns 2 on a malformed invocation, 1 if any GENUINE
    survivor remains after full-selection reverification, 0 otherwise
    (no survivors reported, or every reported survivor was recovered).
    """
    if len(argv) < _MIN_ARGC:
        print(
            "usage: mutation_recheck_survivors.py <mutants_dir> <test_path> "
            "[test_path ...]   (reads `mutmut results` output on stdin)",
            file=sys.stderr,
        )
        return 2

    mutants_dir = Path(argv[0])
    full_test_selection = argv[1:]
    survivors = parse_survivors(sys.stdin.read())

    outcomes = recheck_all_survivors(
        survivors,
        full_test_selection,
        mutants_dir=mutants_dir,
        base_env=dict(os.environ),
        runner=runner,
    )
    print(format_report(outcomes))
    return 1 if any_genuine_survivors(outcomes) else 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
