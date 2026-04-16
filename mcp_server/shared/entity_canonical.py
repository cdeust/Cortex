"""Entity name canonicalization — pre-insert case dedup policy.

Source: Curie I4 completeness audit (2026-04-16) found **111 case-variant
duplicate entity groups** on the cortex DB (`Output`/`OUTPUT`,
`String`/`STRING`, `DOMAIN`/`domain`, `FilePath`/`filepath`, etc.) across
196 entity rows. The extraction layer was inserting raw names without
case normalization, so each variant produced a new row.

Policy (2026-04-16):

    canonical(name) = name.title() if name is ALL-CAPS AND length ≥ 4
                      else name   (preserve)

Rationale for the length ≥ 5 cutoff:
    - Iconic short acronyms (HTTP, JSON, YAML, HTML, CURL, BASH, XML,
      CSS, URL, GPT, AI, ML) are semantically load-bearing in all-caps
      form; converting `HTTP` → `Http` breaks reader expectation.
    - Longer all-caps tokens (OUTPUT, STRING, DOMAIN, STATUS, ERROR,
      DEBUG, MACRO) are almost always accidental shout-case — the same
      concept was captured as Title-case elsewhere.
    - A 5-char cutoff preserves HTTP/JSON/YAML/HTML/CURL while collapsing
      HTTPS → Https (the convention Python stdlib uses in `urllib.parse`
      variants and Go's `net/http` uses in type names).

Trade-offs documented explicitly so the policy is reversible:
    - We lose `HTTPS` / `XHTML` / `MACRO` as preserved acronyms.
    - We gain dedup of ~111 duplicate groups on a typical store, which
      was silently corrupting the co-access graph (a memory mentioning
      `Output` and a memory mentioning `OUTPUT` produced no co-access
      edge because the entity IDs differed).

The canonicalizer is a pure function (no I/O, stdlib only) and lives in
the shared layer so both the insert path (`pg_store_entities.insert_entity`
and its sqlite sibling) and the migration script can reference the same
rule. Changes to the policy require updating this file + the migration
test together.
"""

from __future__ import annotations

# Threshold above which ALL-CAPS tokens are considered accidental
# shout-case rather than intentional acronyms. 5 keeps HTTP/JSON/YAML/
# HTML/CURL intact and collapses HTTPS/XHTML/STORE/DEBUG/OUTPUT/STRING.
_ALLCAPS_TITLE_CUTOFF = 5


def canonicalize_entity_name(name: str) -> str:
    """Return the canonical form of an entity name per the dedup policy.

    Examples (doctest-style — mirrored in tests/):
        canonicalize_entity_name("OUTPUT")    == "Output"
        canonicalize_entity_name("STRING")    == "String"
        canonicalize_entity_name("DOMAIN")    == "Domain"
        canonicalize_entity_name("output")    == "output"   # preserve lower
        canonicalize_entity_name("Output")    == "Output"   # preserve title
        canonicalize_entity_name("HTTP")      == "HTTP"     # 4-char acronym
        canonicalize_entity_name("JSON")      == "JSON"     # 4-char acronym
        canonicalize_entity_name("HTML")      == "HTML"     # 4-char acronym
        canonicalize_entity_name("HTTPS")     == "Https"    # 5-char → title
        canonicalize_entity_name("XHTML")     == "Xhtml"    # 5-char → title
        canonicalize_entity_name("FilePath")  == "FilePath" # preserve camel
        canonicalize_entity_name("file_path") == "file_path" # preserve snake
        canonicalize_entity_name("__init__")  == "__init__" # preserve dunder
        canonicalize_entity_name("")          == ""          # empty passes
    """
    if not name:
        return name
    stripped = name.strip()
    if not stripped:
        return stripped
    # ALL-CAPS detection must tolerate digits and underscores (e.g.,
    # `HTTP_2`, `PHASE_3`, `A1B2`) — if the alpha chars are all upper and
    # at least one exists, treat as all-caps for policy purposes.
    alpha_chars = [c for c in stripped if c.isalpha()]
    if not alpha_chars:
        return stripped  # e.g., "42" or "__" — no letters, no conversion
    if all(c.isupper() for c in alpha_chars) and len(stripped) >= _ALLCAPS_TITLE_CUTOFF:
        # Title-case only the alpha segments — preserve underscores/digits
        # so `HTTP_CLIENT` becomes `Http_Client` not `Http_client`.
        return stripped.title()
    return stripped
