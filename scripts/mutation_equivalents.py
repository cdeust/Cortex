#!/usr/bin/env python3
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

from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
REGISTRY_PATH = REPO_ROOT / "memory" / "mutation-equivalents.json"

# An entry states *why* it can never be killed, and the two kinds age
# differently. `equivalent-by-construction` is a claim about the code's
# semantics and cannot become false. `unreachable-branch` is a claim about the
# current callers or grammar and CAN become false when either changes — which
# is exactly when the diff-pinning above forces a re-read.
KINDS = frozenset(
    {
        "equivalent-by-construction",
        "unreachable-branch",
        "seam-pending-implementation",
    }
)

_MIN_RATIONALE = 40  # a sentence, not a shrug
_SURVIVOR = re.compile(r"^\s*([\w.]+):\s*survived\s*$")


class RegistryError(ValueError):
    """The registry file is malformed. Never silently tolerated."""


@dataclass(frozen=True)
class Equivalent:
    """One registered, justified, un-killable mutant."""

    mutant: str
    removed: str
    added: str
    kind: str
    rationale: str
    issue: str

    @property
    def module(self) -> str:
        """`mcp_server.core.ast_extractors` from the mutant's dotted name."""
        return self.mutant.rsplit(".", 1)[0]

    @property
    def source_path(self) -> str:
        return self.module.replace(".", "/") + ".py"


def _require(entry: dict, field: str, index: int) -> str:
    value = entry.get(field)
    if not isinstance(value, str) or not value.strip():
        raise RegistryError(
            f"entry {index}: '{field}' is required and must be non-empty"
        )
    return value


def parse_registry(text: str) -> list[Equivalent]:
    """Parse and validate the registry. Raises rather than skipping bad rows."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:  # noqa: TRY003 — message carries the position
        raise RegistryError(f"not valid JSON: {exc}") from exc
    rows = data.get("equivalents")
    if not isinstance(rows, list):
        raise RegistryError("top-level 'equivalents' must be a list")

    out: list[Equivalent] = []
    seen: set[str] = set()
    for i, entry in enumerate(rows):
        if not isinstance(entry, dict):
            raise RegistryError(f"entry {i}: must be an object")
        kind = _require(entry, "kind", i)
        if kind not in KINDS:
            raise RegistryError(
                f"entry {i}: unknown kind {kind!r}; expected one of {sorted(KINDS)}"
            )
        rationale = _require(entry, "rationale", i)
        if len(rationale) < _MIN_RATIONALE:
            raise RegistryError(
                f"entry {i}: rationale is {len(rationale)} chars; "
                f"at least {_MIN_RATIONALE} required — state why it cannot be killed"
            )
        mutant = _require(entry, "mutant", i)
        if mutant in seen:
            raise RegistryError(f"entry {i}: duplicate mutant {mutant!r}")
        seen.add(mutant)
        out.append(
            Equivalent(
                mutant=mutant,
                removed=_require(entry, "removed", i),
                added=_require(entry, "added", i),
                kind=kind,
                rationale=rationale,
                issue=_require(entry, "issue", i),
            )
        )
    return out


def load_registry(path: Path = REGISTRY_PATH) -> list[Equivalent]:
    if not path.exists():
        return []
    return parse_registry(path.read_text(encoding="utf-8"))


def parse_survivors(text: str) -> list[str]:
    """Mutant names whose status is exactly 'survived'."""
    names: list[str] = []
    for line in text.splitlines():
        m = _SURVIVOR.match(line)
        if m and m.group(1) not in names:
            names.append(m.group(1))
    return names


def mutant_diff(mutant: str, cwd: Path = REPO_ROOT) -> tuple[str, str]:
    """The (removed, added) source lines of one mutant, via `mutmut show`."""
    proc = subprocess.run(  # noqa: PLW1510 — a failed show yields ("", "") and is reported as a mismatch
        ["uv", "run", "mutmut", "show", mutant],
        capture_output=True,
        text=True,
        cwd=cwd,
    )
    removed = added = ""
    for line in proc.stdout.splitlines():
        if line.startswith("---") or line.startswith("+++"):
            continue
        if line.startswith("-") and not removed:
            removed = line[1:].strip()
        elif line.startswith("+") and not added:
            added = line[1:].strip()
    return removed, added


@dataclass(frozen=True)
class Verdict:
    accepted: list[tuple[str, Equivalent]]
    unregistered: list[str]
    mismatched: list[tuple[str, Equivalent]]
    stale: list[Equivalent]

    @property
    def ok(self) -> bool:
        return not (self.unregistered or self.mismatched or self.stale)


def classify(
    survivors: list[str],
    registry: list[Equivalent],
    diffs: dict[str, tuple[str, str]],
    mutated_paths: frozenset[str],
) -> Verdict:
    """Split survivors into accepted / unregistered / drifted, and find rot.

    `mutated_paths` scopes the staleness check: a scoped run mutates a few
    files, so entries for files it never touched are not stale, they are
    simply out of scope.
    """
    by_name = {e.mutant: e for e in registry}
    accepted: list[tuple[str, Equivalent]] = []
    unregistered: list[str] = []
    mismatched: list[tuple[str, Equivalent]] = []

    for name in survivors:
        entry = by_name.get(name)
        if entry is None:
            unregistered.append(name)
            continue
        removed, added = diffs.get(name, ("", ""))
        if (removed, added) == (entry.removed, entry.added):
            accepted.append((name, entry))
        else:
            mismatched.append((name, entry))

    survived = set(survivors)
    stale = [
        e
        for e in registry
        if e.source_path in mutated_paths and e.mutant not in survived
    ]
    return Verdict(accepted, unregistered, mismatched, stale)


def format_report(v: Verdict) -> str:
    lines: list[str] = []
    if v.accepted:
        by_kind: dict[str, int] = {}
        for _, e in v.accepted:
            by_kind[e.kind] = by_kind.get(e.kind, 0) + 1
        summary = ", ".join(f"{n} {k}" for k, n in sorted(by_kind.items()))
        lines.append(
            f">>> {len(v.accepted)} registered equivalent(s) accepted: {summary}"
        )
    if v.mismatched:
        lines.append(
            f"!!! {len(v.mismatched)} registered mutant(s) NO LONGER MATCH "
            "their recorded diff."
        )
        lines.append(
            "!!! mutmut numbers mutants positionally, so the code moved and the "
            "rationale is unverified. Re-read each and update or remove the entry."
        )
        for name, e in v.mismatched:
            lines.append(
                f"      {name}\n        registered: {e.removed!r} -> {e.added!r}"
            )
    if v.stale:
        lines.append(f"!!! {len(v.stale)} registry entr(ies) match no produced mutant.")
        lines.append(
            "!!! Either a test now kills it (delete the entry) or the code moved "
            "(the rationale is unverified). Both need a human."
        )
        for e in v.stale:
            lines.append(f"      {e.mutant}")
    if v.unregistered:
        lines.append(
            f"!!! {len(v.unregistered)} UNREGISTERED surviving mutant(s) "
            "— a real test gap:"
        )
        for name in v.unregistered:
            lines.append(f"      {name}")
    if v.ok and not v.accepted:
        lines.append("  none — 0 surviving mutants 🎉")
    elif v.ok:
        lines.append("  no unregistered survivors 🎉")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
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
    if not argv:
        print("usage: mutation_equivalents.py <mutated_source.py> ...", file=sys.stderr)
        return 2
    try:
        registry = load_registry()
    except RegistryError as exc:
        print(f"!!! registry is malformed: {exc}", file=sys.stderr)
        return 2

    survivors = parse_survivors(sys.stdin.read())
    diffs = {name: mutant_diff(name) for name in survivors}
    verdict = classify(survivors, registry, diffs, frozenset(argv))
    print(format_report(verdict), file=sys.stderr)
    for name in verdict.unregistered:
        print(f"    {name}: survived")
    return 1 if (verdict.mismatched or verdict.stale) else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
