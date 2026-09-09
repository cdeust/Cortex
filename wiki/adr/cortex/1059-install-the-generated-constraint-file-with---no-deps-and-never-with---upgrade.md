---
created: 2026-09-09T10:47:34Z
kind: adr
number: 1059
status: accepted
tags: [packaging, pip, uv-lock, concurrency, installer]
title: Install the generated constraint file with --no-deps and never with --upgrade
---
# ADR-1059: Install the generated constraint file with --no-deps and never with --upgrade

## Status

accepted

## Context

`scripts/setup.sh` step 3/7 installs `requirements/setup.txt` into `$DEPS_DIR` with `pip install --target`. That file is the complete dependency closure exported from `uv.lock` by `scripts/generate_pip_constraints.py`, fully pinned and hashed.

Two forces meet at this one call site.

First, pip must not re-derive the graph. `pyproject.toml` declares `[tool.uv] override-dependencies = ["mpmath>=1.4.1,<1.5"]`, mirrored in `uv.lock`, which deliberately pushes mpmath past the `mpmath<1.4,>=1.1.0` bound `sympy 1.14.0` still declares in its own metadata. uv's resolver honours the override; the `requirements.txt` format has no way to carry it. Left to itself, pip re-validates every listed package against the rest of the file, sees only an unresolvable conflict, and aborts with `ResolutionImpossible`. ADR-0800 recorded this when PR #332 hit it; that fix corrected every consumer except this one, which stayed broken until the plugin installer failed on it (PR #539).

Second, this directory is shared with a possibly running process. `.claude-plugin/plugin.json` runs `install-plugin.sh` as the plugin postInstall, so the script executes inside a live Claude Code session where the MCP server may hold `DEPS_DIR` on `sys.path`. ADR-0749 exists for exactly this: `scripts/launcher_deps_install.py` resolves into a `.tmp-{pid}` scratch directory and commits entry by entry through `os.replace` with rollback, to keep a running server out of pip's rmtree/replace path.

The tempting cure for a stale `deps/` is `--upgrade`, since without it pip skips any package whose directory already exists and reports success anyway, so the step can never refresh anything. That cure was tried and rejected on review: it hands pip's delete-then-rewrite to the shared directory with no lock and no atomicity, reintroducing the hazard ADR-0749 was built to remove, and it would repair on every run whatever the launcher's version-only, ABI-blind idempotence guard reintroduces, hiding that defect instead of fixing it.

## Decision

Install every generated constraint file with `--no-deps`. The file is the complete uv-resolved closure; pip re-deriving it is never correct and breaks whenever a `[tool.uv]` override steers a package past a bound another package's metadata still declares.

Do not pass `--upgrade` at this call site. Skip-if-present is safe under concurrency by construction; replace-in-place is not, and this script runs as a postInstall inside a live session. Refreshing a stale `deps/` is the launcher's responsibility, through the atomic commit path of ADR-0749, not pip's.

Stale entries that survive an interpreter change are tracked separately as a defect in that guard, not worked around here.

## Consequences

Easier: the installer's dependency step is reproducible and matches the twelve other consumers of a generated constraint file (ci.yml, release.yml, the composite test-suite action, three Dockerfiles, `scripts/launcher_torch_cpu.py`). A reader of any one of them sees the same shape.

Easier: the concurrency contract around `deps/` now has a single owner. Nothing outside `scripts/launcher_deps_install.py` mutates entries in place.

Harder: `scripts/setup.sh` cannot repair a stale `deps/` itself. After an interpreter upgrade the directory can hold extension modules built for the previous ABI, and the step will report success regardless. That is a known gap, deliberately left visible rather than papered over, and it depends on the launcher's idempotence guard becoming ABI-aware.

Risk accepted: a maintainer who deletes either flag gets no signal from CI, because nothing asserts the invariant that a hashed constraint install also passes `--no-deps`. That absence is precisely why PR #332's fix could skip a call site, and it is filed as its own gate work.
