# ADR-0771: scripts/mutation_equivalents.py implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `scripts/mutation_equivalents.py`; original SHA-256 `23cfed2f90e7915bf0bec9e59589b099ae7d6d65e19fc092f05cdc71bc5bbd98`.

## Original docstring, lines 2–30

````text
"""Registered-equivalent gate for mutation testing — coding-standards §12.4.

The standard is "0 surviving non-equivalent mutants, or each survivor
documented as equivalent". `scripts/mutation_check.sh` could express the first
half and not the second: it failed on any survivor, so a module where every
survivor carries a written rationale looked exactly like one nobody had
examined. That makes the blocking per-commit tier unusable on such a module
for even a one-line change, which in practice means it gets bypassed.

This adds the missing half without reopening the hole the gate exists to
close. Three properties, in order of importance:

**Fail-closed on drift.** mutmut names mutants positionally
(`x__walk_type__mutmut_16`), so the same name means a *different* mutation
after the function changes. Registering a name alone would silently absolve
whatever later occupies that slot. Every entry therefore pins the exact
`removed`/`added` line pair, and an exemption applies only when the diff still
matches. A changed mutation is an unregistered survivor and fails.

**Fail-closed on absence.** Only listed mutants are exempt. There is no
wildcard, no per-file suppression and no "ignore this module" — those are how
a suppression mechanism becomes the next false green.

**No silent rot.** An entry that no longer corresponds to a produced mutant is
an error, not a shrug: either the code moved (so the rationale is unverified)
or a test now kills it (so the entry is dead weight). Both need a human.

Registry: `memory/mutation-equivalents.json`.
"""
````

## Original comment, lines 44–48

````text
# An entry states *why* it can never be killed, and the two kinds age
# differently. `equivalent-by-construction` is a claim about the code's
# semantics and cannot become false. `unreachable-branch` is a claim about the
# current callers or grammar and CAN become false when either changes — which
# is exactly when the diff-pinning above forces a re-read.
````

## Original docstring, lines 96–96

````text
"""Parse and validate the registry. Raises rather than skipping bad rows."""
````

## Original docstring, lines 268–280

````text
"""stdin: `mutmut results` output. argv: the mutated source paths.

    stdout carries the UNREGISTERED survivor names, one per line, so the caller
    can hand exactly those to `mutation_recheck_survivors.py` — the order
    matters. The registry must filter first: a mutant the recheck would
    reclassify as RECOVERED is not in the registry, and running the registry
    check second would report it as an unjustified survivor. Filtering known
    equivalents first, then re-verifying only what is left, composes correctly.

    stderr carries the human report. The exit code covers only the failures
    this script alone can judge — a drifted or stale entry — because whether an
    unregistered survivor is real is the recheck's call, not ours.
    """
````

