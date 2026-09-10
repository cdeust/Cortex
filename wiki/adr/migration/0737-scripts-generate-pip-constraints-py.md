# ADR-0737: scripts/generate_pip_constraints.py implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `scripts/generate_pip_constraints.py`; original SHA-256 `1ca5c929d4fc839d69bc883ceae0473bf0441eaf1b08a6ff954d6ad84aeb33f6`.

## Original docstring, lines 2–25

````text
"""Generate the hash-pinned requirements files every pip install reads.

Why these files exist
---------------------
`pip install foo==1.2.3` is NOT pinned. An exact version still resolves to
whatever artifact the index serves under that version today; only a hash
pins the bytes. OpenSSF Scorecard's Pinned-Dependencies check encodes
exactly this distinction — it treats any pip invocation without
`--require-hashes` as unpinned, and it is right to.

`--require-hashes` is all-or-nothing: once any hash is supplied, every
requirement including transitive ones must carry one. That is only
tractable from a resolved lock, which is why each file here is exported
from uv.lock rather than hand-maintained. Hand-maintaining them would
reintroduce the drift this replaces: scripts/setup.sh carried a copy of the
dependency list that had already drifted from pyproject.toml
(`sentence-transformers>=2.2.0` against a real floor of `>=3.0.0`).

The table of files and their consumers is scripts/pip_constraint_sets.py.

Usage:
    python3 scripts/generate_pip_constraints.py           # rewrite if changed
    python3 scripts/generate_pip_constraints.py --check   # exit 1 if stale
"""
````

## Original comment, lines 48–50

````text
# PyPI serves no local versions (`2.13.0+cpu`), by policy — PEP 440 local
# identifiers are rejected on upload. So a local-version pin always comes
# from some other index, and always needs that index named.
````

## Original docstring, lines 61–67

````text
"""Every url a `[[tool.uv.index]]` entry in pyproject.toml declares.

    Read rather than restated so a directive written into a generated file
    cannot name an index the project never opted into. A regex and not
    tomllib because this repository's floor is Python 3.10, where tomllib
    does not exist.
    """
````

## Original docstring, lines 92–103

````text
"""The indexes this export's local-version pins cannot be installed without.

    uv resolves a `+cpu` wheel from a `[[tool.uv.index]]` but emits no index
    directive into the export, and pip defaults to PyPI alone — where that
    version does not exist. Without this, `pip install -r` fails outright
    with `No matching distribution found for torch==2.13.0+cpu`.

    Derived per file rather than declared per file on purpose: the declared
    form drifted the first time it was written (three of the nine files that
    needed the directive carried it), and the six that did not were each
    consumed by a linux runner, where the marker is live.
    """
````

## Original docstring, lines 143–151

````text
"""Run uv and return its raw stdout. The ONLY part that touches the world.

    Split from `compose` deliberately. When locating uv, running it, and
    judging its output all lived in one function, the uv-presence guard ran
    before everything else — so no test could reach the validation rules
    without a real uv on PATH, and the unit suite acquired a hidden
    dependency on an external binary. Every job that ran pytest then had to
    install uv to keep tests that never needed it passing.
    """
````

## Original comment, lines 249–250

````text
# "Could not run" and "found drift" are different outcomes and must not
    # share an exit code: a missing uv would otherwise read as a clean gate.
````

