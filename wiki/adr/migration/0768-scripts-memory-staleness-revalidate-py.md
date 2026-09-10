# ADR-0768: scripts/memory_staleness_revalidate.py implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `scripts/memory_staleness_revalidate.py`; original SHA-256 `952f3e6f29e438f333b885c73193000e69564622ca39e820a8a705431f538715`.

## Original docstring, lines 2–23

````text
"""Re-validate file-existence staleness for memories — fleet-watch #110.

Runs ``handlers.consolidation.memory_staleness_pass`` against the shared store:
for every non-stale, file-referencing memory whose referenced paths no longer
resolve on disk, sets ``is_stale=TRUE`` (mark-only; never de-stales — see the
pass docstring). This makes the staleness the injection banners surface
(age · grade · stale) actually fire, instead of waiting for a manual
``validate_memory`` run.

Usage
-----

Dry-run (default) — report what would be marked, write nothing::

    uv run python scripts/memory_staleness_revalidate.py

Apply the change to the DB::

    uv run python scripts/memory_staleness_revalidate.py --apply

Idempotent: a re-run skips rows already marked stale (``include_stale=False``).
"""
````

