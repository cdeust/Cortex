# ADR-0770: scripts/mutation_check.sh implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `scripts/mutation_check.sh`; original SHA-256 `9bab6bb1ba65f6bf3ddd169bc86190cbd659669ba1a0e3d0b65eec31f07bc432`.

## Original shell-comment, lines 2–29

````text
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

````

## Original shell-comment, lines 51–55

````text
# Repoint only_mutate, source_paths and the test selection at the change under
# test. source_paths must contain the roots the sources live under: mutmut only
# copies those into mutants/, and a source outside them is silently never
# mutated — the run then reports 0 survivors because it mutated nothing. Rooted
# at the committed value so a run inside mcp_server/ keeps its existing scope.

````

## Original shell-comment, lines 79–91

````text
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

````

## Original shell-comment, lines 113–123

````text
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

````

