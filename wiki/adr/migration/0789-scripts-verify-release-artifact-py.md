# ADR-0789: scripts/verify_release_artifact.py implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `scripts/verify_release_artifact.py`; original SHA-256 `c389b15e49369b6ed7a88d67248f3981d6c6b7d1d1ddd7cc5d7ade90eda3c608`.

## Original docstring, lines 2–25

````text
"""Verify a downloaded release artifact against its published SHA-256.

Issue #178, acceptance criterion 4. Cortex reads and persists every session
transcript and installs session hooks with the user's full filesystem access;
a substituted wheel or bundle is a keylogger on the user's engineering work.
The release workflow now publishes a ``<asset>.sha256`` companion for every
GitHub Release asset (wheel, sdist, SBOM). This module is the *consumer* side:
an install path that downloads a release asset can verify it before trusting
it, and a user can run it by hand.

Scope, stated honestly (§8, no theater):
  * The MARKETPLACE install path consumes the git tree directly
    (``${CLAUDE_PLUGIN_ROOT}``, ADR-0050); its integrity is the git commit
    plus the tag's build-provenance attestation, not a downloaded checksum.
  * The PYPI path installs through ``pip``, which verifies distributions
    against PyPI's own recorded hashes (and PEP 740 attestations when the
    installer supports them). This module does NOT duplicate that.
  * What this module covers is the third path: fetching a raw asset from the
    GitHub Release (e.g. the SBOM, or a wheel pulled outside pip). That is the
    one download with no built-in hash check, so it is the one that gets one.

Standard library only: this may run before the plugin's own dependencies exist
on ``sys.path`` (same constraint as the ``launcher_deps_*`` modules).
"""
````

## Original comment, lines 34–34

````text
# source: FIPS 180-4 (SHA-256 digest is 32 bytes -> 64 lowercase hex chars).
````

## Original comment, lines 36–38

````text
# Read the artifact in fixed-size chunks so a multi-hundred-MB wheel (the ML
# stack) is hashed with bounded memory rather than a single read into RAM.
# source: measured — 1 MiB balances syscall count against resident memory.
````

