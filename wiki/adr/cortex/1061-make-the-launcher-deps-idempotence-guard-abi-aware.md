---
created: 2026-09-09T00:00:00Z
kind: adr
number: 1061
status: accepted
tags: [packaging, deps-dir, abi, installer, launcher]
title: Make the launcher deps idempotence guard ABI-aware
---
# ADR-1061: Make the launcher deps idempotence guard ABI-aware

## Status

accepted

## Context

`scripts/launcher_deps_install.py::_entry_already_satisfied` (ADR-0749) exists
to protect a locked, already-correct transitive dependency — numpy under a
running MCP server is the named case — from ever entering the
rmtree/replace commit path: if the destination's `.dist-info` already
carries the exact version pip just resolved, the entry is skipped.

That predicate compares versions only. A version can be unchanged across an
interpreter upgrade while the compiled artifact cannot: CPython bakes an
interpreter-ABI tag into every non-stable-ABI extension's filename
(`speedups.cpython-313-darwin.so`), and nothing in the guard, or anywhere
else in the commit path, ever reads it.

Reproduced on this machine after moving `deps/` from Python 3.13 to 3.14
without a `pyproject.toml`/`uv.lock` version bump for the affected packages:

- `deps/websockets/speedups.cpython-313-darwin.so`,
  `deps/watchfiles/...`, `deps/caio/thread_aio.cpython-313-darwin.so`, and
  `deps/cffi`'s backend all kept their 3.13 build. `PYTHONPATH=deps python3
  -c "import websockets.speedups"` failed under 3.14.
- `deps/_cffi_backend.cpython-313-darwin.so` sat next to a correctly-tagged
  `deps/_cffi_backend.cpython-314-darwin.so` — a `--target` install's
  standalone extension module (never wrapped in a package directory) has no
  `.dist-info` of its own and no top-level entry ever revisits it once
  committed, so it survives every subsequent run as dead weight; reverting
  `deps/` back to 3.13 would have silently resumed loading it.

ADR-1059 named this gap and deliberately declined to work around it at the
`scripts/setup.sh` call site: `--upgrade` there would hand pip's
delete-then-rewrite to a directory a live MCP server may hold on
`sys.path`, reintroducing exactly the hazard ADR-0749 removed. The fix
belongs in the guard itself.

## Decision

`_entry_already_satisfied` now checks two conditions, in order: the
version match ADR-0749 already required, and — only once that is true,
since the filesystem walk below is the more expensive check — that the
destination entry, walked recursively, carries no extension module tagged
for an interpreter ABI other than the one currently running
(`launcher_deps_fs.entry_has_foreign_abi_extension`, `is_foreign_abi_extension`).
A foreign-ABI tag routes the entry through the SAME atomic commit path a
version bump already used (`commit_entry`'s backup-then-replace), so a
whole package directory containing a stale extension is swapped in one
step rather than patched file-by-file.

The ABI check is relative to the interpreter that is CURRENTLY RUNNING
(`sysconfig.get_config_var("EXT_SUFFIX")`), not to some value baked into
`tmp_dir`'s fresh build — pip always resolves for the running interpreter,
so the freshly-downloaded copy is definitionally never foreign. The
untagged `.abi3.so`/`.so`/`.pyd` suffixes are deliberately excluded from
the "foreign" classification: those are the stable-ABI or source-shared
forms and are compatible across interpreter builds by construction.

A second, separate sweep — `launcher_deps_fs.prune_foreign_abi_extensions`
— runs once a whole commit batch has succeeded (same place
`prune_superseded_dist_info` already runs) and removes any TOP-LEVEL file
in `deps_dir` that is a foreign-ABI extension. This closes the second
shape: a standalone module the per-entry loop never revisits because its
old and new names differ. The running interpreter can never load a
foreign-ABI file regardless of whether some other package still needs it,
so deleting it is safe by construction, not merely a heuristic.

## Consequences

Easier: a `deps/` directory survives an interpreter upgrade without manual
intervention — the next `ensure_deps`/`ensure_all_deps` run repairs every
version-unchanged package whose compiled artifact predates the switch, and
sweeps the orphaned standalone modules left behind.

Easier: ADR-0749's original protection is untouched — a package whose
version AND ABI both already match is still skipped, so a locked,
already-correct transitive dependency under a running MCP server is never
touched.

Harder: the guard now does a bounded filesystem walk (`os.walk`) per
version-matched entry instead of a pure dict lookup. Bounded by the size
of one package's install tree, and only reached after the cheap version
check already passed, so the added cost is proportional to what would
otherwise be silently wrong.

Risk accepted: the ABI-tag regex is CPython-specific
(`cpython-<ver>-<platform>` / Windows `cp<ver>-<platform>`); a non-CPython
interpreter this project doesn't target would see no tagged extensions to
misclassify in the first place, so it degrades to a no-op rather than a
false positive.
