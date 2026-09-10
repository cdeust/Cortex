"""Entity name canonicalization — pre-insert case dedup policy.

source: ADR-0648"""

from __future__ import annotations

# source: ADR-0648


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
        # source: ADR-0648

        return stripped.title()
    return stripped
