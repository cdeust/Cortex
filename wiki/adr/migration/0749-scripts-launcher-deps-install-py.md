# ADR-0749: scripts/launcher_deps_install.py implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `scripts/launcher_deps_install.py`; original SHA-256 `a311896e4a8a7cab95a679d1a0acfcd4bd55b4e5c4819fe8a9ed44b7fa7c3fe4`.

## Original docstring, lines 2–15

````text
"""Pip invocation and non-destructive commit — stdlib only.

Split out of ``scripts/launcher_deps.py`` for SRP and the 500-line
file-size rule: this module owns the two I/O-heavy steps of a
dependency install — spawning ``pip`` into a scratch dir and committing
its result into ``deps_dir`` one entry at a time — while
``launcher_deps.py`` owns the higher-level policy (stamping, locking,
when to call this at all) and ``launcher_deps_fs.py`` owns pure
filesystem primitives this module reads/writes through.

Like its siblings, this module runs before the plugin's own
dependencies exist on ``sys.path`` and may import only the Python
standard library.
"""
````

## Original comment, lines 33–33

````text
# source: pre-W2-5 pip_install retained the last 2000 characters of pip errors.
````

## Original docstring, lines 38–59

````text
"""Drop the ``[extra]`` clause from a pip spec, keeping the version.

    Precondition: ``spec`` is a pip requirement string. Postcondition: the
    return value carries no extras clause; everything else is unchanged.

    pip documents constraints files as version-only and now rejects extras
    outright, so ``psycopg[binary]==3.3.4`` (BASE_PACKAGES) failed the whole
    ML install — silently, since only that install passes constraints:
    FlashRank never landed and recall degraded to first-stage scores.

    Stripping preserves the intent rather than changing it — a constraint
    pins the VERSION a shared transitive resolves to, and pip applies it to
    the distribution however its extras were requested; extras belong on the
    install target (which still carries them), not on the constraint.

    # source: https://pip.pypa.io/en/stable/user_guide/#constraints-files
    #   ("only control which version of a requirement is installed")
    # source: measured 2026-08-02 — pip 26.0.1/py3.14 aborted the plugin's
    #   ML install with "ERROR: Constraints cannot have extras"; reproduced
    #   on pip 25.2/py3.13 (`--dry-run --no-index -c <BASE_PACKAGES>`), so
    #   the range is not pip-26-only. Both accept the stripped file.
    """
````

## Original docstring, lines 91–107

````text
"""Move one top-level ``tmp_dir`` entry into ``deps_dir``.

    Precondition: ``entry`` is a direct child name of both ``tmp_dir``
    (must exist there) and, if present, ``deps_dir``.
    Postcondition: returns ``None`` on success (dest now holds the new
    entry, any pre-existing dest was moved to a same-directory backup
    which is then removed) or the backup path on FAILURE, in which case
    dest has been restored to its PRE-CALL state (rollback) and the
    caller is responsible for NOT deleting ``tmp_dir`` so ``entry``'s
    freshly-downloaded copy survives for a retry.

    Non-destructive by construction (issue #97 suggestion 2): the
    previous version's ``rmtree(dest)`` before ``os.replace`` meant a
    mid-loop failure left dest permanently deleted with nothing to
    restore. Renaming dest aside first means the ORIGINAL bytes are
    still on disk until the replace has actually succeeded.
    """
````

## Original docstring, lines 134–137

````text
"""Idempotence guard (issue #97 suggestion 1): true iff ``dest``
    already has the exact version ``tmp_dir`` resolved for ``entry`` --
    protects a locked, already-correct transitive dep (e.g. numpy under
    a running MCP server) from ever entering the rmtree/replace path."""
````

## Original docstring, lines 144–162

````text
"""Commit every top-level ``tmp_dir`` entry into ``deps_dir``.

    Precondition: ``tmp_dir`` holds a completed, successful pip
    ``--target`` install. Postcondition: ``(True, None)`` iff every
    entry committed (or was already satisfied) and every stale
    ``*.dist-info`` sibling has been pruned; ``(False, failed_entry)`` on
    the first commit failure, with NO dist-info pruned and ``deps_dir``
    restored for every entry processed so far.

    Issue #149: ``os.listdir`` order is unspecified by the stdlib and
    differs by OS/filesystem; a single distribution spans two entries
    here (its ``.dist-info`` and its package directory), and the batch
    is only atomic at the whole-``tmp_dir`` level (stops at the first
    failure). Pruning the OLD dist-info per-entry, immediately after ITS
    OWN commit, let an ordering where the dist-info committed before the
    package directory delete the still-valid old metadata and then hit
    the package-directory failure/rollback -- so the prune below now
    waits for the whole batch to confirm success.
    """
````

