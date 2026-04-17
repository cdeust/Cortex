"""Phase 7: content ingestion hardening.

Applied at every user-input boundary (remember, ingest_*, backfill) to
prevent three classes of defect:

  1. Unicode duplicate memories (NFC normalization).
     "café" written as U+00E9 vs "cafe" + U+0301 hash-mismatches and
     creates ghost duplicates. NFC composes to the precomposed form
     consistently.

  2. ReDoS amplification via adversarially long content.
     Content is capped at CONTENT_MAX_BYTES (default 1 MB). A single
     1-MB payload hitting a vulnerable regex can block the event loop
     for seconds. Truncation is silent but logged via stderr.

  3. Unicode control / format characters that break tsvector /
     downstream DOM rendering. We strip:
       - C0 controls except \\t \\n \\r
       - C1 controls (U+0080–U+009F)
       - BOM / ZWNBSP (U+FEFF)
       - Bidi-override overrides (trojan source — CVE-2021-42574)

Source:
  * Unicode Standard Annex #15 (Normalization Forms)
  * CVE-2021-42574 (Trojan Source bidi override injection)
  * docs/program/phase-5-pool-admission-design.md §7 (hardening)
"""

from __future__ import annotations

import logging
import re
import unicodedata

logger = logging.getLogger(__name__)

# 1 MB default. Environment override: CORTEX_MEMORY_CONTENT_MAX_BYTES.
CONTENT_MAX_BYTES = 1 * 1024 * 1024

# Stripped: C0 controls except \t \n \r, all C1 controls, BOM/ZWNBSP,
# Unicode bidi overrides.
_BIDI_OVERRIDES = "\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069"
_STRIP_RE = re.compile(
    r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\ufeff" + _BIDI_OVERRIDES + r"]"
)


def harden_content(content: str, *, max_bytes: int = CONTENT_MAX_BYTES) -> str:
    """Apply the full content-hardening pipeline at ingestion.

    Returns the hardened string. Callers should use the returned value,
    not the input — truncation, normalization, and stripping are all
    potentially observable.

    Precondition: ``content`` is a str (not bytes). Accepts empty
    strings and returns them unchanged.
    """
    if not content:
        return ""

    hardened = _strip_control_chars(content)
    hardened = unicodedata.normalize("NFC", hardened)
    hardened = _cap_bytes(hardened, max_bytes)
    return hardened


def _strip_control_chars(s: str) -> str:
    """Remove C0/C1 controls (except \\t \\n \\r), BOM, bidi overrides."""
    return _STRIP_RE.sub("", s)


def _cap_bytes(s: str, max_bytes: int) -> str:
    """Truncate to <= max_bytes when UTF-8 encoded. Logs at truncation.

    We encode, slice bytes, then decode with errors='ignore' so the
    result is always valid UTF-8 (no orphaned continuation bytes).
    """
    encoded = s.encode("utf-8")
    if len(encoded) <= max_bytes:
        return s
    logger.warning(
        "Content truncated from %d bytes to %d at ingestion",
        len(encoded),
        max_bytes,
    )
    return encoded[:max_bytes].decode("utf-8", errors="ignore")
