#!/usr/bin/env python3
"""Validate a native host receipt: every check is bound to the artifact it ran.

A native receipt records what a real installed host (Claude Code, Codex) did
against Cortex. Issue #730 found that the committed receipts do not tie each
check to the artifact that ran it: the v4.23.4 receipt names a version, the
2026-09-22 handoff names none, so a check measured on a source checkout could
be read as support for a distributed wheel. This schema closes that gap.

Schema ``cortex-native-receipt/1`` (one JSON object):

- ``artifact``: the running ``mcp_server`` as ``cortex doctor`` names it
  (``mcp_server/doctor_artifact.py``): ``kind`` (``wheel`` or ``source-tree``),
  ``version``, ``revision`` (git sha of a source tree, ``null`` for a wheel or a
  tree outside git), ``modified`` (``mcp_server`` differs from ``revision``) and
  ``members_digest`` (64 hex characters, the doctor's digest).
- ``platform``: ``os``, ``os_version``, ``arch``.
- ``backend``: the storage the host used (free text, e.g. ``managed PostgreSQL``).
- ``hosts``: ``[{"name", "version"}]``, the installed hosts that ran.
- ``checks``: ``[{"id", "host", "outcome", "artifact_digest", "evidence"}]``;
  ``outcome`` is ``passed`` or ``failed``; ``artifact_digest`` must equal
  ``artifact.members_digest`` and ``host`` must name an entry of ``hosts``, so a
  receipt cannot merge checks run on two different artifacts or hosts.

``validate`` returns the schema errors (empty when the receipt is valid). A
valid receipt is *distributed* evidence only for an unmodified wheel; a source
tree is source evidence, the label the doctor already gives it. ``coverage``
lists which of #730's required journeys the receipt passes, so the claim gate
(the next slice of #730) can refuse a support cell that lacks one.

source: issue #730 (remaining slice 1: a receipt schema that binds each native
check to the artifact digest it ran); issue #729 (artifact identity)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

SCHEMA = "cortex-native-receipt/1"  # source: this module's docstring (v1)
KINDS = ("wheel", "source-tree")  # source: doctor_artifact.py _identify branches
OUTCOMES = ("passed", "failed")  # source: issue #730 (a receipt records failures)
# source: doctor_artifact.members_digest, a sha256 hexdigest (64 hex characters)
_DIGEST = re.compile(r"[0-9a-f]{64}")
# source: issue #730 acceptance evidence, items 2 to 4 (one id per journey)
REQUIRED_CHECKS = (
    "cross-host-transfer",
    "project-exclusion",
    "startup-context",
    "capture",
    "session-persistence",
    "compaction-recovery",
    "hook-trust",
    "unicode",
    "dependency-failure",
    "teardown",
    "tool-output-conversion",
)
_FIELDS = {
    "artifact": ("kind", "version", "revision", "modified", "members_digest"),
    "platform": ("os", "os_version", "arch"),
}


def _missing(where: str, value: Any, keys: tuple[str, ...]) -> list[str]:
    if not isinstance(value, dict):
        return [f"{where}: expected an object"]
    return [f"{where}.{key}: missing" for key in keys if key not in value]


def _artifact_errors(artifact: dict) -> list[str]:
    errors = []
    if artifact["kind"] not in KINDS:
        errors.append(f"artifact.kind: {artifact['kind']!r} is not one of {KINDS}")
    if not isinstance(artifact["members_digest"], str) or not _DIGEST.fullmatch(
        artifact["members_digest"]
    ):
        errors.append("artifact.members_digest: not a 64-character sha256 hex")
    if not isinstance(artifact["modified"], bool):
        errors.append("artifact.modified: expected true or false")
    if artifact["kind"] == "wheel" and artifact["revision"] is not None:
        errors.append("artifact.revision: a wheel has no git revision, use null")
    return errors


def _check_errors(index: int, check: Any, digest: str, hosts: set) -> list[str]:
    where = f"checks[{index}]"
    keys = ("id", "host", "outcome", "artifact_digest", "evidence")
    errors = _missing(where, check, keys)
    if errors:
        return errors
    if check["outcome"] not in OUTCOMES:
        errors.append(f"{where}.outcome: {check['outcome']!r} not in {OUTCOMES}")
    if check["artifact_digest"] != digest:
        errors.append(f"{where}.artifact_digest: differs from artifact.members_digest")
    if check["host"] not in hosts:
        errors.append(f"{where}.host: {check['host']!r} is not listed in hosts")
    if not str(check["evidence"]).strip():
        errors.append(f"{where}.evidence: empty")
    return errors


def _host_names(hosts: Any) -> tuple[set, list[str]]:
    if not isinstance(hosts, list) or not hosts:
        return set(), ["hosts: expected a non-empty list"]
    errors: list[str] = []
    for index, host in enumerate(hosts):
        errors += _missing(f"hosts[{index}]", host, ("name", "version"))
    names = {h["name"] for h in hosts if isinstance(h, dict) and "name" in h}
    return names, errors


def validate(receipt: Any) -> list[str]:
    """The schema errors of ``receipt`` (an empty list when it is valid)."""
    if not isinstance(receipt, dict):
        return ["receipt: expected a JSON object"]
    if receipt.get("schema") != SCHEMA:
        return [f"schema: expected {SCHEMA!r}, got {receipt.get('schema')!r}"]
    errors: list[str] = []
    for section, keys in _FIELDS.items():
        errors += _missing(section, receipt.get(section), keys)
    if "backend" not in receipt:
        errors.append("backend: missing")
    hosts, host_errors = _host_names(receipt.get("hosts"))
    errors += host_errors
    checks = receipt.get("checks")
    if not isinstance(checks, list) or not checks:
        errors.append("checks: expected a non-empty list")
    if errors:
        return errors
    errors += _artifact_errors(receipt["artifact"])
    digest = receipt["artifact"]["members_digest"]
    for index, check in enumerate(checks):
        errors += _check_errors(index, check, digest, hosts)
    return errors


def is_distributed(receipt: dict) -> bool:
    """True when a valid receipt ran an unmodified wheel (distributed evidence)."""
    artifact = receipt["artifact"]
    return artifact["kind"] == "wheel" and not artifact["modified"]


def coverage(receipt: dict) -> dict[str, list[str]]:
    """Which required journeys a valid receipt passed, failed, or lacks."""
    outcomes: dict[str, set] = {}
    for check in receipt["checks"]:
        outcomes.setdefault(check["id"], set()).add(check["outcome"])
    report: dict[str, list[str]] = {"passed": [], "failed": [], "missing": []}
    for check_id in REQUIRED_CHECKS:
        seen = outcomes.get(check_id)
        if not seen:
            report["missing"].append(check_id)
        elif "failed" in seen:
            report["failed"].append(check_id)
        else:
            report["passed"].append(check_id)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("receipt", type=Path, help="receipt JSON file")
    args = parser.parse_args(argv)
    try:
        receipt = json.loads(args.receipt.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"{args.receipt}: cannot read the receipt: {exc}", file=sys.stderr)
        return 2
    errors = validate(receipt)
    for error in errors:
        print(f"{args.receipt}: {error}", file=sys.stderr)
    if errors:
        return 1
    report = {"distributed": is_distributed(receipt), **coverage(receipt)}
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
