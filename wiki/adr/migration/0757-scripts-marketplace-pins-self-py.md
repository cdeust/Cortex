# ADR-0757: scripts/marketplace_pins_self.py implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `scripts/marketplace_pins_self.py`; original SHA-256 `cb7e62e8979c3287fb0ab722617d341f22998e4294aab5709b375ffda4970340`.

## Original docstring, lines 1–8

````text
"""Local-source (self-hosted-in-this-repo) pin checks for the marketplace gate.

Split out of check_marketplace_pins.py (issue: that file crossed the
300-line §4.1 cap once REGISTRY_VERSION_STALE was added). Covers pins
shaped ``{"source": "./some/path", "version": ...}`` — a plugin whose code
lives in this repo, checked against this repo's own ``plugin.json`` and
git tags rather than a remote GitHub API.
"""
````

## Original comment, lines 22–24

````text
# source: audited 2026-07-25 (Cortex PR #182 review clause 5) and 2026-08-04
# (Cortex PR #351 Opus review) — each legacy identity is a notice-only shim
# frozen at its rename release; advancing one would hide the migration boundary.
````

