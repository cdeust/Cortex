---
created: 2026-09-15T20:59:23Z
kind: adr
number: 1063
status: accepted
tags: [packaging, pip, installer, concurrency, issue-573]
title: Route the installers' dependency step through the launcher's scratch-and-commit install
---
# ADR-1063: Route the installers' dependency step through the launcher's scratch-and-commit install

## Status

accepted

## Context

`scripts/setup.sh` (the `--postgres` path of `install-plugin.sh`) and `scripts/setup.py` (the SQLite path) installed `requirements/setup.txt` with `pip install --target "$DEPS_DIR" --no-deps --require-hashes`, straight into the persistent `$CLAUDE_PLUGIN_DATA/deps`. ADR-1059 kept that call without `--upgrade` because the directory may sit on a running MCP server's `sys.path`, and it named the launcher's atomic commit path (ADR-0749) as the only one allowed to refresh a stale `deps/`.

Without `--upgrade`, pip skips every top-level package directory that already exists but still writes the new `*.dist-info`. On the 4.21.0 → 4.22.0 upgrade of 2026-09-15 (issue #573) this left sentence-transformers 5.6.1 code under 5.6.1 and 6.0.1 metadata, transformers 5.14.1 under two dist-infos, and tokenizers and huggingface_hub mixed, and verification failed on `tokenizers>=0.22.0,<=0.23.0 ... found tokenizers==0.23.2`. So the skip-if-present call was safe under concurrency and wrong across versions. The ADR-1059 consequence "setup.sh cannot repair a stale deps/ itself" turned out to cover every pinned-version upgrade, not only an interpreter change.

The launcher already has the correct upgrade path: `scripts/launcher_deps_install.py` installs into a `deps.tmp-<pid>` scratch directory, commits entry by entry through `os.replace` with rollback, then prunes superseded `*.dist-info` siblings once the whole batch has committed. That path had one blind spot for a directory an old installer already damaged: `dist_info_versions` mapped each distribution to whichever `*.dist-info` `os.listdir` returned last, so with the pinned one listed last the idempotence guard read the old package directory as satisfied and skipped it.

## Decision

Both installers install `requirements/setup.txt` through the launcher. `scripts/launcher_deps.py` gains `install_requirements(deps_dir, requirements)`, also runnable as `python3 scripts/launcher_deps.py --requirement FILE DEPS_DIR`. It takes the same `deps.lock` as the launcher's own bootstrap, runs pip with `--no-deps --require-hashes -r FILE` into the scratch target (`launcher_pip.install_requirements`), and commits through the existing `_commit_resolved_entries`. `scripts/setup.sh` step 3 lives in `scripts/lib/install_python_deps.sh` and calls that entry point; `scripts/setup.py` calls it as a subprocess. Nothing in either installer runs `pip install --target` on the deps directory any more.

A distribution with more than one `*.dist-info` in a directory has no known installed version: `dist_info_versions` omits it, so neither the commit guard nor `dist_info_satisfies` ever treats it as satisfied, and the next install replaces every entry of it.

ADR-1059 still holds for the flags: `--no-deps` and `--require-hashes` on every generated constraint file, and never `--upgrade`.

## Consequences

Easier: an upgrade leaves exactly one `*.dist-info` per distribution, matching the pin, and the package code under it is the pinned version. A deps directory damaged by a 4.22.0 upgrade is repaired by re-running `install-plugin.sh`, whichever order the filesystem lists its entries in. `tests_py/scripts/test_installer_upgrade_single_version.py` drives both installers with real pip, offline, from version N and from the mixed state, and asserts this.

Easier: `deps/` has one writer policy. The installers and the launcher share the lock, the scratch directory, the rollback and the pruning, so an install during a live session never hands pip's delete-then-rewrite to a directory a server has on `sys.path`.

Harder: the installers inherit the launcher's pip environment (`launcher_pip.clean_environment`): inherited `PIP_INDEX_URL`, `PIP_EXTRA_INDEX_URL`, `PIP_FIND_LINKS` and pip configuration files are ignored, and pip is pointed at `https://pypi.org/simple/`, as the runtime bootstrap already was. A requirements file can still carry its own index options.

Harder: a re-run on an up-to-date directory is no longer a no-op for entries whose name is not their distribution's. The idempotence guard matches a top-level entry to a version by name, so `yaml` (PyYAML), `sklearn`, `google`, `bin` and similar entries are replaced on every run, with identical content, through the same atomic rename. Measured on 2026-09-15 on an APFS clone of the maintainer's 4.22.0 deps directory (Python 3.14.4, macOS 26): 27 of 213 entries replaced, every one of them of that kind; entries named after their distribution, numpy among them, kept their inode. Mapping entries to distributions through each `RECORD` would remove the churn; that is a change to the guard, not to this routing.

Unchanged: a top-level module that an old version shipped and the new one no longer ships is not removed, because no scratch entry replaces it. This was already true of the launcher's own installs.
