"""Parses `docs/module-inventory.md` § Dependency Rules into layer rules.

Fixes a DRY violation flagged in review: the previous implementation
hardcoded a Python copy of this table (`FORBIDDEN_SECOND_COMPONENT`), which
diverges from the documented table silently the moment either one changes.
This module makes the markdown table itself the single source of truth —
`craftsmanship_imports.py` derives its whitelist from what this module
parses, never from a second hand-maintained copy.

Table shape (`docs/module-inventory.md`)::

    | Layer | May Import | Must NOT Import |
    |---|---|---|
    | **shared/** | Python stdlib only | core, infrastructure, handlers, server |
    | **core/** | shared/ only | infrastructure, handlers, server, os/pathlib |
    ...

Each row becomes a `LayerRule`:

- ``allowed_layers`` — the TRUE WHITELIST for ``mcp_server.<layer>`` imports,
  taken from the "May Import" column's layer-name tokens. An import to any
  ``mcp_server.*`` layer NOT in this set is a violation — this is the fix
  for the review finding that the old blacklist let `scripts.legacy_bridge`-
  style stray project imports straight through.
- ``is_pure`` — True when the "May Import" cell literally ends in the word
  "only" (``"Python stdlib only"``, ``"shared/ only"``) — a textual signal
  already present in the table, not an invented classification. A pure
  layer forbids third-party packages entirely (Clean Architecture: `core/`
  and `shared/` carry zero I/O and zero framework coupling); a non-pure
  ("boundary") layer — infrastructure, validation, handlers, server, hooks
  — is exactly where adapters and third-party drivers are expected to
  live, so third-party imports there are not a craftsmanship violation.
- ``stdlib_allowed`` — False only for the "nothing" cell (`errors/`);
  stdlib is the ambient default everywhere else, since no layer can avoid
  using the language's own control-flow/typing primitives.
- ``stdlib_denied`` — specific stdlib modules named in "Must NOT Import"
  as a slash-joined list (``"os/pathlib"`` for `core/`) — the one piece of
  information the "May Import" column cannot express on its own.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MODULE_INVENTORY = REPO_ROOT / "docs" / "module-inventory.md"

_TABLE_HEADER = "| Layer | May Import | Must NOT Import |"
_ROW_RE = re.compile(r"^\|\s*\*\*([a-z]+)/\*\*\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*$")
_NOTHING = "nothing"


@dataclass(frozen=True)
class LayerRule:
    name: str
    is_pure: bool
    stdlib_allowed: bool
    allowed_layers: frozenset[str] = field(default_factory=frozenset)
    stdlib_denied: frozenset[str] = field(default_factory=frozenset)


def _strip_parenthetical(token: str) -> str:
    """Drop a trailing "(...)" note, e.g. "infrastructure (except via handlers)"."""
    return re.sub(r"\s*\([^)]*\)\s*$", "", token).strip()


def _tokenize(cell: str) -> list[str]:
    return [_strip_parenthetical(t).rstrip("/").strip() for t in cell.split(",")]


def _parse_may_import(cell: str) -> tuple[frozenset[str], bool, bool]:
    """Return (allowed_layers, stdlib_allowed, is_pure) from a "May Import" cell."""
    if cell.strip().lower() == _NOTHING:
        return frozenset(), False, True
    is_pure = cell.strip().lower().endswith("only")
    cell_body = re.sub(r"\s+only\s*$", "", cell, flags=re.IGNORECASE)
    stdlib_allowed = False
    layers: set[str] = set()
    for token in _tokenize(cell_body):
        if token.lower() == "python stdlib":
            stdlib_allowed = True
        elif token:
            layers.add(token)
    # Boundary layers never name "Python stdlib" explicitly (the table only
    # calls it out for shared/ and infrastructure/) but obviously need it —
    # every layer needs the language's own control-flow/typing primitives.
    # Only a layer whose cell was literally "nothing" (handled above, with
    # stdlib_allowed already False) denies stdlib.
    if not is_pure:
        stdlib_allowed = True
    return frozenset(layers), stdlib_allowed, is_pure


def _parse_must_not_stdlib(cell: str) -> frozenset[str]:
    """Extract stdlib module bans from a "Must NOT Import" cell.

    A token is a stdlib-module list (not a layer reference) when it
    contains an internal "/" — e.g. "os/pathlib" — as opposed to a layer
    reference, which never contains an internal slash in this column (only
    "May Import" ever uses a trailing "layer/" spelling).
    """
    denied: set[str] = set()
    for raw_token in cell.split(","):
        token = _strip_parenthetical(raw_token)
        if "/" in token:
            denied.update(part.strip() for part in token.split("/") if part.strip())
    return frozenset(denied)


def _parse_row(match: re.Match[str]) -> LayerRule:
    name, may_cell, must_not_cell = match.groups()
    allowed_layers, stdlib_allowed, is_pure = _parse_may_import(may_cell)
    stdlib_denied = _parse_must_not_stdlib(must_not_cell)
    # A pure layer whose "Must NOT Import" column names specific stdlib
    # submodules (core/'s "os/pathlib") implicitly allows stdlib in
    # general — banning particular submodules of an already-fully-banned
    # category would otherwise be meaningless prose. Textual evidence from
    # the table itself, not an override: `core/` never says "Python
    # stdlib" the way `shared/` does, yet the Must-Not column only makes
    # sense read this way (also matches coding-standards.md §2.2: "Core/
    # domain -> shared/common + standard library only").
    if stdlib_denied:
        stdlib_allowed = True
    return LayerRule(
        name=name,
        is_pure=is_pure,
        stdlib_allowed=stdlib_allowed,
        allowed_layers=allowed_layers,
        stdlib_denied=stdlib_denied,
    )


def _check_header_present(markdown: str) -> None:
    if _TABLE_HEADER not in markdown:
        raise ValueError(
            f"{MODULE_INVENTORY}: '§ Dependency Rules' table header not found "
            f"— expected {_TABLE_HEADER!r}"
        )


def _extract_row_lines(markdown: str) -> list[str]:
    """Return the table's raw data-row lines (header separator excluded).

    Only a line that ISN'T EVEN TRYING to be a table row (doesn't start
    with ``|``) ends the table — the fix for the review finding that a
    prior version treated ANY unmatched line, including a malformed row in
    the MIDDLE of the table, as "the table ended", silently dropping that
    row and every row after it (reproduced: one broken row after
    ``validation/`` silently removed ``errors/``, ``handlers/``,
    ``server/`` and ``hooks/`` from enforcement — four of eight layers,
    zero signal, no error).
    """
    rows: list[str] = []
    in_table = False
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped == _TABLE_HEADER:
            in_table = True
            continue
        if not in_table:
            continue
        if not stripped.startswith("|"):
            break  # genuine end of table: not even attempting to be a row
        if stripped.startswith("|---"):
            continue  # header separator row
        rows.append(line)
    return rows


def parse_layer_rules(markdown: str) -> dict[str, LayerRule]:
    """Parse the § Dependency Rules table into layer name -> LayerRule.

    Fails loudly and completely, never partially — see
    ``_extract_row_lines`` for why a malformed row raises instead of
    silently truncating the table, and the row-count check below (a
    structural self-check independent of that one) for why a duplicate
    layer name silently overwriting an earlier dict entry also raises.
    Also raises if the table header itself is missing (section renamed or
    removed) or matched but produced zero rows.
    """
    _check_header_present(markdown)
    row_lines = _extract_row_lines(markdown)
    rules: dict[str, LayerRule] = {}
    for line in row_lines:
        match = _ROW_RE.match(line)
        if match is None:
            raise ValueError(
                f"{MODULE_INVENTORY}: table row does not match the expected "
                f"'| **layer/** | ... | ... |' shape: {line!r} — refusing to "
                f"silently drop this row and every row after it"
            )
        rule = _parse_row(match)
        rules[rule.name] = rule
    if not rules:
        raise ValueError(
            f"{MODULE_INVENTORY}: matched the table header but parsed no rows"
        )
    if len(rules) != len(row_lines):
        raise ValueError(
            f"{MODULE_INVENTORY}: parsed {len(rules)} layer rule(s) from "
            f"{len(row_lines)} table row line(s) — a duplicate layer name "
            f"silently overwrote an earlier row"
        )
    return rules


def load_layer_rules(
    module_inventory_path: Path = MODULE_INVENTORY,
) -> dict[str, LayerRule]:
    return parse_layer_rules(module_inventory_path.read_text(encoding="utf-8"))


def is_stdlib(top_level: str) -> bool:
    return top_level in sys.stdlib_module_names
