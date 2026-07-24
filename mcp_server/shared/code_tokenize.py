"""Code-aware sub-token splitting for FTS indexing and query expansion.

Cortex memories frequently carry code identifiers — ``normalizePaymentAmount``,
``snake_case_id``, ``HTTPRequest``. SQLite's FTS5 ``unicode61`` tokenizer treats
each of those as ONE opaque token, so a natural-language query for ``payment``
never matches a memory that only wrote ``normalizePaymentAmount``.

FTS5 custom tokenizers require a compiled C extension (the ``fts5_tokenizer``
API is not reachable from Python's ``sqlite3``). This module achieves the same
effect purely in Python, on both sides of the index:

  * **index time** — ``augment_content`` appends the sub-tokens of every
    identifier to the text handed to ``memories_fts``, so ``payment`` becomes a
    first-class indexed term alongside the original ``normalizePaymentAmount``.
  * **query time** — ``expand_fts_query`` rewrites each query word into an
    ``("word" OR "sub1" OR "sub2")`` group, so a query that *contains* a
    camelCase identifier still matches memories that stored the split words.

Reference concept: the ``cbm_camel_split`` FTS5 tokenizer in the
codebase-memory-mcp project (C). This is the same split rule (camelCase +
snake_case + digit boundaries), realised as content/query rewriting rather than
a native tokenizer.

Pure utility — no I/O, no domain knowledge. Shared layer (stdlib only).
"""

from __future__ import annotations

import re

# A "word" for query purposes: a maximal run of letters/digits/underscore. This
# mirrors what unicode61 treats as a single token before our splitting.
_WORD_RE = re.compile(r"[A-Za-z0-9_]+")

# Sub-token boundaries, applied in order:
#   1. underscores / hyphens  → snake_case, kebab-case
#   2. lower→Upper transition → camelCase        (paymentAmount → payment|Amount)
#   3. Upper-run→Upper+lower  → acronym boundary (HTTPRequest  → HTTP|Request)
#   4. letter↔digit transition                    (utf8 → utf|8)
_CAMEL_1 = re.compile(r"(.)([A-Z][a-z]+)")  # boundary 3
_CAMEL_2 = re.compile(r"([a-z0-9])([A-Z])")  # boundary 2
_DIGIT = re.compile(r"([A-Za-z])([0-9])|([0-9])([A-Za-z])")  # boundary 4


def split_identifier(token: str) -> list[str]:
    """Split one identifier into its lowercase sub-tokens.

    precondition: ``token`` is a str.
    postcondition: returns a list of lowercase alphanumeric sub-tokens with no
    empty strings; a token with no internal boundary yields ``[token.lower()]``;
    the split is deterministic and idempotent (splitting a sub-token is a no-op).

    Examples: ``normalizePaymentAmount`` → ``[normalize, payment, amount]``;
    ``snake_case_id`` → ``[snake, case, id]``; ``HTTPRequest`` → ``[http,
    request]``; ``utf8`` → ``[utf, 8]``.
    """
    if not token:
        return []
    # snake / kebab first so camel rules see clean segments
    text = token.replace("_", " ").replace("-", " ")
    text = _CAMEL_1.sub(r"\1 \2", text)
    text = _CAMEL_2.sub(r"\1 \2", text)
    text = _DIGIT.sub(lambda m: " ".join(p for p in m.groups() if p), text)
    return [p.lower() for p in text.split() if p]


def _extra_subtokens(text: str) -> list[str]:
    """Sub-tokens that are NOT already present as standalone words in ``text``.

    precondition: ``text`` is a str.
    postcondition: returns the deduplicated sub-tokens produced by splitting
    every word of ``text`` whose split is non-trivial (more than one part), in
    first-seen order; single-part words contribute nothing (they already index).
    """
    words = _WORD_RE.findall(text)
    # Seed with words already present verbatim (lowercased) so a sub-token that
    # is also a standalone word is not re-appended.
    seen: set[str] = {w.lower() for w in words}
    extras: list[str] = []
    for word in words:
        parts = split_identifier(word)
        if len(parts) <= 1:
            continue
        for p in parts:
            if p not in seen:
                seen.add(p)
                extras.append(p)
    return extras


def augment_content(text: str) -> str:
    """Return ``text`` with identifier sub-tokens appended for FTS indexing.

    precondition: ``text`` is a str.
    postcondition: returns ``text`` unchanged when it holds no splittable
    identifier; otherwise returns ``text + " " + <space-joined sub-tokens>`` so
    the FTS index carries both the original identifier and its parts. Idempotent
    up to already-present words (sub-tokens already appearing as words are not
    re-appended).
    """
    if not text:
        return text
    extras = _extra_subtokens(text)
    if not extras:
        return text
    return text + " " + " ".join(extras)


def _fts_quote(term: str) -> str:
    """Quote ``term`` as an FTS5 string literal (doubling embedded quotes)."""
    return '"' + term.replace('"', '""') + '"'


def expand_fts_query(query: str) -> str:
    """Rewrite a user query into a sub-token-aware, FTS5-safe MATCH string.

    precondition: ``query`` is a str.
    postcondition: returns an FTS5 MATCH expression that preserves the original
    implicit-AND-across-words semantics (each source word becomes one required
    group) while adding OR-alternatives for the sub-tokens of any camelCase /
    snake_case word. Every term is quoted, so FTS5 operator keywords and
    punctuation in the input become harmless literals. Returns ``""`` when the
    query contains no indexable word (callers already guard the empty MATCH).
    """
    groups: list[str] = []
    for word in _WORD_RE.findall(query):
        parts = split_identifier(word)
        if len(parts) <= 1:
            groups.append(_fts_quote(word.lower()))
        else:
            alts = [word.lower(), *parts]
            # dedupe preserving order
            seen: set[str] = set()
            uniq = [a for a in alts if not (a in seen or seen.add(a))]
            groups.append("(" + " OR ".join(_fts_quote(a) for a in uniq) + ")")
    return " ".join(groups)
