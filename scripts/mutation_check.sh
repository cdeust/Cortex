#!/usr/bin/env bash
#
# Scoped mutation-testing run (mutmut 3.x) — rules/coding-standards.md §12.
# Mutates ONLY the given source file(s) against the given test path, then
# restores pyproject.toml's [tool.mutmut] block untouched. Standard: 0
# surviving non-equivalent mutants on the changed code.
#
#   usage: scripts/mutation_check.sh <test_path> <source.py> [source.py ...]
#   e.g.   scripts/mutation_check.sh tests_py/shared/test_json_native.py \
#                                     mcp_server/shared/json_native.py
#
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [ $# -lt 2 ]; then
  sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'
  exit 2
fi

TESTS="$1"; shift
PY="$ROOT/pyproject.toml"
BAK="$(mktemp)"
cp "$PY" "$BAK"
cleanup() { cp "$BAK" "$PY"; rm -f "$BAK"; rm -rf "$ROOT/mutants" "$ROOT/.mutmut-cache"; }
trap cleanup EXIT

# Repoint only_mutate + the test selection at the change under test. The rest
# of [tool.mutmut] (source_paths, also_copy, use_setproctitle) is preserved.
python3 - "$PY" "$TESTS" "$@" <<'PYEOF'
import re, sys
path, tests, *sources = sys.argv[1], sys.argv[2], *sys.argv[3:]
fmt = lambda xs: "[" + ", ".join(f'"{x}"' for x in xs) + "]"
src = open(path).read()
src, n1 = re.subn(r'^only_mutate = .*$', "only_mutate = " + fmt(sources), src, count=1, flags=re.M)
src, n2 = re.subn(r'^pytest_add_cli_args_test_selection = .*$',
                  "pytest_add_cli_args_test_selection = " + fmt([tests]), src, count=1, flags=re.M)
assert n1 and n2, "pyproject [tool.mutmut] must define only_mutate and pytest_add_cli_args_test_selection"
open(path, "w").write(src)
PYEOF

echo ">>> mutating: $* | tests: $TESTS"
uv run mutmut run
echo ">>> survivors (must be empty, or documented equivalents):"
uv run mutmut results | grep -iE 'survived' || echo "  none — 0 surviving mutants 🎉"
