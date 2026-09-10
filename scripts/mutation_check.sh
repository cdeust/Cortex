#!/usr/bin/env bash
# source: ADR-0770
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

# source: ADR-0770
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

# source: ADR-0770
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

  # source: ADR-0770
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
