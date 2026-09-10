# ADR-0724: scripts/craftsmanship_imports.py implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `scripts/craftsmanship_imports.py`; original SHA-256 `4a8cae417b8dd0c235766aaa48cdf56b7555c1b26553c3f99e7de3a5ede852b3`.

## Original docstring, lines 1–14

````text
"""Craftsmanship rule 3 — layer-boundary imports, a TRUE whitelist.

Rewritten after review found the prior version was a blacklist wearing a
whitelist's name: it denied a short hardcoded list of specific imports
(``os``, ``pathlib``, a few ``mcp_server.<layer>`` prefixes) and silently
ALLOWED everything else — so `import numpy`, `import requests`, and
`import scripts.legacy_bridge` inside `core/` all passed uncaught. The
fix is structural, not a bigger blacklist: every import is now checked
against what a layer is explicitly PERMITTED to reference (derived from
``craftsmanship_layer_table.py``, itself parsed from
``docs/module-inventory.md`` § Dependency Rules — never a second
hardcoded copy of that table); anything not on the permitted list is a
violation, covering all eight documented layers, not four.
"""
````

## Original docstring, lines 52–59

````text
"""Collects absolute, runtime-reachable dotted import module names.

    Relative imports (``from . import x``, ``level > 0``) are skipped: they
    resolve within the same package and cannot cross a layer boundary that
    an absolute ``mcp_server.<layer>`` import would. Imports inside
    ``if TYPE_CHECKING:`` are skipped too — a type-only forward reference
    used for annotations, not a runtime dependency the layer rule polices.
    """
````

## Original docstring, lines 82–88

````text
"""True if ``module`` (dotted, absolute) breaks ``rule``'s whitelist.

    Every branch is a permission CHECK, not a denial check: an import that
    matches none of them falls through to the final ``return True`` — the
    fix for the review finding that a permitted set with an implicit
    "everything else is fine" default is not a whitelist.
    """
````

## Original comment, lines 99–102

````text
# Third-party (neither `mcp_server.*` nor stdlib): permitted only for a
    # "boundary" layer (infrastructure/validation/handlers/server/hooks) —
    # Clean Architecture's adapter layers, where frameworks belong. A
    # "pure" layer (shared/, core/, errors/) forbids it outright.
````

