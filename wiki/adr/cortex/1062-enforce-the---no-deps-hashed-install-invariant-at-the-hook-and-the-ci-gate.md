---
created: 2026-09-09T12:28:40Z
kind: adr
number: 1062
status: accepted
tags: [packaging, pip, hooks, ci, installer]
title: Enforce the --no-deps hashed-install invariant at the hook and the CI gate
---
# ADR-1062: Enforce the --no-deps hashed-install invariant at the hook and the CI gate

## Status

accepted

## Context

`pyproject.toml`'s `[tool.uv] override-dependencies` steers `mpmath` past the
`mpmath<1.4` bound `sympy 1.14.0`'s own metadata still declares. `uv`'s
resolver honours the override when it exports `requirements/*.txt`; the
requirements-file format itself cannot carry it. Installing that file with
`--require-hashes` but without `--no-deps` makes `pip` re-derive the
dependency graph from the unresolved metadata and abort with
`ResolutionImpossible`.

PR #332 fixed exactly this failure across CI, both Dockerfiles, and
`scripts/launcher_torch_cpu.py`, and recorded the mechanism in ADR-0800.
That fix corrected every call site the author then knew about, but missed
`scripts/setup.sh`, which stayed broken for months until the plugin
installer failed on it (fixed in PR #539, ADR-1059). Nothing enforced the
invariant itself — only individual call sites were patched, twice.

`mcp_server/hooks/decision_gate.py` (ADR-1060) is the working precedent in
this repo for a blocking `PreToolUse` hook: it refuses a write at edit time
rather than reporting the defect after it is committed and pushed. The
owner's stated position is that CI verifies too late and hooks are what
should block the action.

A grep-level repo scan and a blocking hook are not exclusive: the hook
catches a Claude Code agent about to write the broken form; the scan
catches everything the hook cannot see — a file already committed before
the hook existed, or a commit made through git directly rather than through
Edit/Write. Both need the same definition of "violates the invariant," or
they will drift apart the way the two originally-separate #332 call sites
did.


## Decision

Add `mcp_server/hooks/_no_deps_lex.py`, a pure, I/O-free lexical detector:
given file text, it merges backslash-continued lines into logical shell
commands, splits each on `&&`/`;`, and flags any command that contains
`--require-hashes` together with a `-r <path containing "requirements" and
ending .txt>` install but does not also contain `--no-deps`.

Two consumers share that one detector:

1. `mcp_server/hooks/no_deps_gate.py` — a `PreToolUse` hook on `Edit`/`Write`,
   registered in `.claude-plugin/plugin.json` alongside `decision_gate`,
   scoped to `scripts/`, `.github/workflows/`, `.github/actions/`,
   `Dockerfile*`, and `.devcontainer/` (the exact set PR #332 and PR #539
   touched). It reconstructs the candidate file content the same way
   `decision_gate` does (reusing its `candidate_content`), scans it, and
   exits 2 to block the write when a violation would be introduced.
   `CORTEX_NO_DEPS_GATE=off` overrides one call, matching `decision_gate`'s
   override convention. Like `decision_gate`, it fails open on anything it
   cannot read or parse: a false negative here is cheap, a hook that makes
   editing impossible is not.

2. `scripts/check_no_deps_invariant.py` — a repo-wide CI gate, wired into
   `.github/workflows/ci.yml`'s `craftsmanship` job next to
   `check_craftsmanship.py`. It enumerates tracked files under the same
   scope via `git ls-files`, scans each with the identical detector, and
   exits 1 on any violation. It also accepts explicit file paths (matching
   `check_craftsmanship.py`'s CLI shape) for direct invocation.

The scope check (`in_scope`) is a single function in `no_deps_gate.py`,
imported by the CI script rather than duplicated, so the hook and the scan
can never disagree about which files are in scope.


## Consequences

A new instance of the #332/#539 failure is now refused before it is
written, and a violation from any other path (a direct git commit, a
pre-existing file) fails CI instead of surfacing as a `ResolutionImpossible`
error on someone's next fresh install. The detector is lexical (line/segment
based), not a full shell parser: it does not track quoting or variable
expansion, so a deliberately obfuscated invocation could evade it. This
mirrors `decision_gate`'s own shape-not-semantics tradeoff and is
acceptable for the same reason — the goal is to catch the mistake that
actually recurred (writing the flags without `--no-deps` in the open), not
to defend against adversarial CI-file edits, which the branch-protection
and review process already covers. The detector also does not follow the
Python argument-list style used by `scripts/setup.py` and
`scripts/launcher_torch_cpu.py` (they build the `-r` path from a variable,
not a literal `requirements/*.txt` string, so they were never in the
grep-level pattern's reach); those two call sites are unaffected by this
gate and remain correct by construction (verified by
`tests_py/scripts/test_setup_py_installs_from_lock.py` and
`tests_py/scripts/test_launcher_torch_cpu.py`).
