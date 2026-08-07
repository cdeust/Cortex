#!/usr/bin/env bash
#
# Scoped mutation-testing run (mutmut 3.x) — rules/coding-standards.md §12.
# Mutates ONLY the given source file(s) against the given test path(s), then
# restores pyproject.toml's [tool.mutmut] block untouched. Standard: 0
# surviving non-equivalent mutants on the changed code.
#
#   usage: scripts/mutation_check.sh <test_paths> <source.py> [source.py ...]
#   e.g.   scripts/mutation_check.sh tests_py/shared/test_json_native.py \
#                                     mcp_server/shared/json_native.py
#   <test_paths> may be a single file or a space-separated list quoted as
#   one argument, e.g. "tests_py/a/test_a.py tests_py/b/test_b.py" — a
#   module mutated by more than one test file needs its full selection
#   here (see the eager-import re-verification note below; issue #269).
#
# Any mutant mutmut itself reports "survived" is re-verified against the
# FULL test selection above before being trusted (scripts/
# mutation_recheck_survivors.py): mutmut's per-mutant test attribution is
# recorded once, from the first test whose coverage trace reaches the
# mutated line. A module that builds a dispatch table eagerly at import
# time (memoizing the built closures) is invisible to that attribution
# for every later test, so mutmut narrows the per-mutant rerun to just
# the first (often irrelevant) test and reports "survived" even when the
# full suite kills the mutant — issue #269's root cause, reproduced and
# fixed there. A mutant the full selection actually kills is reported as
# RECOVERED, never silently folded into "killed": the false-survivor
# cause must stay visible to the reader (issue #269 acceptance criterion
# 2), not just absorbed.
#
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [ $# -lt 2 ]; then
  sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'
  exit 2
fi

TESTS="$1"; shift
read -r -a TEST_ARR <<< "$TESTS"
PY="$ROOT/pyproject.toml"
BAK="$(mktemp)"
cp "$PY" "$BAK"
RUN_LOG="$(mktemp)"
cleanup() {
  cp "$BAK" "$PY"; rm -f "$BAK" "$RUN_LOG"
  rm -rf "$ROOT/mutants" "$ROOT/.mutmut-cache"
}
trap cleanup EXIT

# Repoint only_mutate, source_paths and the test selection at the change under
# test. source_paths must contain the roots the sources live under: mutmut only
# copies those into mutants/, and a source outside them is silently never
# mutated — the run then reports 0 survivors because it mutated nothing. Rooted
# at the committed value so a run inside mcp_server/ keeps its existing scope.
python3 - "$PY" "${TEST_ARR[@]}" -- "$@" <<'PYEOF'
import re, sys
args = sys.argv[2:]
sep = args.index("--")
tests, sources = args[:sep], args[sep + 1:]
path = sys.argv[1]
fmt = lambda xs: "[" + ", ".join(f'"{x}"' for x in xs) + "]"
src = open(path).read()
roots = sorted({s.split("/", 1)[0] for s in sources})
declared = re.search(r'^source_paths = \[(.*)\]$', src, flags=re.M)
existing = re.findall(r'"([^"]+)"', declared.group(1)) if declared else []
src, n1 = re.subn(r'^only_mutate = .*$', "only_mutate = " + fmt(sources), src, count=1, flags=re.M)
src, n2 = re.subn(r'^pytest_add_cli_args_test_selection = .*$',
                  "pytest_add_cli_args_test_selection = " + fmt(tests), src, count=1, flags=re.M)
src, n3 = re.subn(r'^source_paths = .*$',
                  "source_paths = " + fmt(sorted(set(existing) | set(roots))), src, count=1, flags=re.M)
assert n1 and n2 and n3, "pyproject [tool.mutmut] must define only_mutate, source_paths and pytest_add_cli_args_test_selection"
open(path, "w").write(src)
PYEOF

echo ">>> mutating: $* | tests: $TESTS"
uv run mutmut run 2>&1 | tee "$RUN_LOG"

# Two independent counts of the same quantity, cross-checked before any verdict.
#
# `mutmut run`'s progress line ends with a 🙁 tally; `mutmut results` lists the
# survivors by name. Trusting the listing alone once produced a FALSE GREEN: on
# a five-file run this script printed "none — 0 surviving mutants 🎉" while the
# progress line ended at `🙁 423` and `mutmut results` in fact returned a
# 915-line non-empty listing (issue #369). A mutation gate that can report clean
# when it is not is worse than no gate, because the ledger row it produces is
# believed. The cleanup trap wipes mutants/ and .mutmut-cache on exit, so a
# disagreement is uninvestigable after the fact — it has to be caught here.
#
# Fail closed: if the two sources disagree, this script refuses to render a
# verdict at all rather than picking the friendlier number.
TALLY="$(tr '\r' '\n' < "$RUN_LOG" | grep -oE '🙁 [0-9]+' | tail -1 | grep -oE '[0-9]+' || true)"
TALLY="${TALLY:-0}"

echo ">>> mutmut-reported survivors (must be empty, or documented equivalents):"
RESULTS="$(uv run mutmut results)"
LISTED="$(printf '%s\n' "$RESULTS" | grep -cE ': *survived[[:space:]]*$' || true)"

if [ "$TALLY" != "$LISTED" ]; then
  {
    echo "!!! survivor-count disagreement — refusing to report a verdict."
    echo "!!!   mutmut run progress line : $TALLY survived"
    echo "!!!   mutmut results listing   : $LISTED survived"
    echo "!!! One of the two is wrong. Re-run mutmut by hand WITHOUT this script"
    echo "!!! (it deletes mutants/ and .mutmut-cache on exit) and inspect the cache."
  } >&2
  exit 2
fi

if [ "$LISTED" -gt 0 ]; then
  printf '%s\n' "$RESULTS" | grep -E ': *survived[[:space:]]*$'

  # Registered equivalents first, re-verification second. The order is load-
  # bearing: a mutant the #269 recheck would reclassify as RECOVERED is not in
  # the registry, so running the registry check on what the recheck already
  # cleared would be fine, but running the recheck on registered equivalents
  # wastes a full test selection per mutant and reports them as genuine.
  # Filter what is justified, then re-verify only what is left.
  #
  # §12.4 is "0 surviving NON-EQUIVALENT mutants, or each survivor documented".
  # Before this, the second half was inexpressible: any survivor failed, so a
  # module whose every survivor carried a rationale looked identical to one
  # nobody had read, and the blocking tier became something to bypass.
  echo ">>> checking survivors against the registered-equivalents registry:"
  set +e
  UNREGISTERED="$(printf '%s\n' "$RESULTS" \
    | uv run python3 "$ROOT/scripts/mutation_equivalents.py" "$@")"
  REG_RC=$?
  set -e
  [ "$REG_RC" -eq 2 ] && exit 2          # malformed registry: never tolerated
  [ "$REG_RC" -eq 1 ] && exit 1          # drifted or stale entry: needs a human

  if [ -z "$UNREGISTERED" ]; then
    echo "  every survivor is a registered, justified equivalent 🎉"
    exit 0
  fi

  echo ">>> re-verifying the UNREGISTERED ones against the FULL test selection (issue #269):"
  printf '%s\n' "$UNREGISTERED" | uv run python3 "$ROOT/scripts/mutation_recheck_survivors.py" "$ROOT/mutants" "${TEST_ARR[@]}"
else
  echo "  none — 0 surviving mutants 🎉"
fi
