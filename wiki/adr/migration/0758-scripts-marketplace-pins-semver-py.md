# ADR-0758: scripts/marketplace_pins_semver.py implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `scripts/marketplace_pins_semver.py`; original SHA-256 `a3fdb044650096f794ef7e06026baceefc6423d3784c7781f3dc1aefc3dad194`.

## Original docstring, lines 1–7

````text
"""Semver parsing + local git-tag helpers for the marketplace pin gate.

Split out of check_marketplace_pins.py (issue: that file crossed the
300-line §4.1 cap once REGISTRY_VERSION_STALE was added). Offline, reads
git only — the PIN_BEHIND_TAG detection path (AP #67) depends on this
staying dependency-free of the network-facing modules.
"""
````

