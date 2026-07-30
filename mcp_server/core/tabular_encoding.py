"""Tabular (columns-once, rows-as-arrays) encoding for homogeneous MCP lists.

A homogeneous result list — every item a dict sharing the same field set —
repeats every key on every item when serialized as an array of objects. For
a recall response of N memories that is N copies of ``"id"``, ``"content"``,
``"score"``, ``"heat"``, … on the wire. The tabular encoding declares the
column names ONCE and streams each item as an array of cells in column order,
so the field names are paid for once instead of N times. The saving grows with
N and with the number of fields; it is exactly the field-name overhead removed.

Reference: cdeust/automatised-pipeline ``src/token_surface.rs`` (issue AP-#56),
itself an AP-idiomatic reimplementation of the TOON tabular encoding in
DeusData/codebase-memory-mcp ``src/mcp/compact_out.h`` (columns-once,
rows-as-arrays). This is the Cortex-Python reimplementation: it stays
JSON-valued (a client needs no bespoke parser), emits a ``columns`` header plus
arrays-of-cells, and self-describes with a ``format`` field so the response
declares its own encoding.

Composition with the response budget (issue #170, contract #1): this transform
runs AFTER ``response_budget.bound_payload`` has performed selection /
condensation / water-filling on the object form, and re-checks the SAME budget
before adopting the tabular shape — it composes with the budget, it does not
bypass it. Because columns-once is never larger than repeated-keys for lists of
two or more items, the re-check only ever declines the degenerate single-item
case (where the object form already fit).

Heterogeneous degradation (issue #170, contract #3): water-filling marks
condensed items with extra ``truncated`` / ``content_length`` keys, so the list
handed here is not always uniform. Columns are therefore the UNION of every
item's keys (first-seen order), and a row carries an explicit ``null`` for any
column that item lacks. This is lossless for the homogeneous case (no absent
fields → no nulls) and honest for the mixed case (absent materializes as a
falsy null, never a fabricated value). No information is lost: every field of
every item is recoverable by column position (see ``decode_tabular``).
"""

from __future__ import annotations

from typing import Any

from mcp_server.core.response_budget import MAX_RESPONSE_CHARS, serialized_length

# The two self-describing encodings a response can declare under ``format``.
FORMAT_JSON = "json"
FORMAT_TABULAR = "tabular"

# Chars the self-describing ``format`` field adds to a payload in the worst
# case (``,"format":"tabular"``). This transform runs AFTER  # noqa: ERA001
# ``bound_payload`` has already filled the payload up to the budget, so the
# field it appends would overshoot the host cap unless that many chars were
# reserved first.
# Callers bound against ``reserved_budget(cap)`` so the appended field lands
# inside the cap. source: exact serialized length of the widest ``format``
# key/value pair (the ``columns`` header is not reserved here — the tabular
# branch re-checks the FULL budget and falls back to json when it would not
# fit, and json is guaranteed to fit by this reservation).
SELF_DESCRIBE_RESERVE_CHARS = len(',"format":"tabular"')


def reserved_budget(budget_chars: int) -> int:
    """The budget to hand ``bound_payload`` so the later ``format`` field fits.

    precondition: ``budget_chars`` is the host cap the final payload must not
    exceed. postcondition: returns ``budget_chars`` minus the worst-case
    ``format``-field cost (never below zero), so a payload bounded to the
    result still fits the cap once ``encode_within_budget`` appends its
    self-describing field.
    """
    return max(0, budget_chars - SELF_DESCRIBE_RESERVE_CHARS)


def parse_format(value: Any) -> str:
    """Normalize a caller-supplied ``format`` argument.

    precondition: none. postcondition: returns ``FORMAT_TABULAR`` iff
    ``value`` is exactly the string ``"tabular"``; every other value
    (including ``None`` and unknown strings) returns ``FORMAT_JSON`` — the
    unchanged default. An unknown format is not an error: it degrades to the
    richest encoding rather than rejecting the call.
    """
    return FORMAT_TABULAR if value == FORMAT_TABULAR else FORMAT_JSON


def derive_columns(items: list[dict]) -> list[str]:
    """The column header: the union of every item's keys, first-seen order.

    precondition: every element of ``items`` is a dict. postcondition: the
    result contains each key that appears in at least one item exactly once,
    ordered by first appearance while scanning items in order. First-seen
    (not sorted) order keeps the common case — a uniform list — presenting
    columns in the natural key order the producer emitted.
    """
    columns: list[str] = []
    seen: set[str] = set()
    for item in items:
        for key in item:
            if key not in seen:
                seen.add(key)
                columns.append(key)
    return columns


def encode_rows(items: list[dict], columns: list[str]) -> list[list[Any]]:
    """Project each item onto ``columns`` as a cell array.

    precondition: every element of ``items`` is a dict; ``columns`` is the
    output of ``derive_columns(items)`` (a superset of every item's keys).
    postcondition: returns one list per item, length ``len(columns)``, where
    cell ``j`` is ``item[columns[j]]`` if present else ``None``. Item order
    and cell order are preserved, so an upstream ranking or paging contract
    is untouched.
    """
    return [[item.get(col) for col in columns] for item in items]


def decode_tabular(columns: list[str], rows: list[list[Any]]) -> list[dict]:
    """Inverse of ``encode_rows`` — reconstruct the objects from the table.

    precondition: every row has length ``len(columns)``. postcondition:
    returns one dict per row mapping ``columns[j] -> row[j]``, so every field
    of every original item is recovered by column position (the
    no-information-loss guarantee; absent-in-original fields come back as the
    explicit ``None`` the encoder wrote). Used by round-trip tests and any
    client that prefers objects.
    """
    # strict=True: the documented precondition above already requires every
    # row to have length len(columns).
    return [dict(zip(columns, row, strict=True)) for row in rows]


def encode_within_budget(
    payload: dict,
    list_key: str,
    fmt: str,
    budget_chars: int = MAX_RESPONSE_CHARS,
) -> dict:
    """Self-describe ``payload`` and, when asked, tabularize its list.

    precondition: ``payload`` is a dict already within ``budget_chars`` in its
    object form (``bound_payload`` ran first); ``fmt`` is a ``parse_format``
    result. postcondition: ``payload["format"]`` is always set. When ``fmt``
    is ``FORMAT_TABULAR`` AND ``payload[list_key]`` is a non-empty list of
    dicts AND the tabular form fits ``budget_chars``, returns a dict whose
    ``list_key`` holds cell-arrays, with a ``columns`` header and
    ``format="tabular"``. Otherwise the object form is returned unchanged with
    ``format="json"``. The budget re-check is what makes this compose with —
    not bypass — the response budget: a degenerate list whose tabular form
    would overflow keeps the object form that already fit.
    """
    payload["format"] = FORMAT_JSON
    if fmt != FORMAT_TABULAR:
        return payload
    items = payload.get(list_key)
    if not isinstance(items, list) or not items:
        return payload
    if not all(isinstance(item, dict) for item in items):
        return payload
    columns = derive_columns(items)
    candidate = {
        **payload,
        list_key: encode_rows(items, columns),
        "columns": columns,
        "format": FORMAT_TABULAR,
    }
    if serialized_length(candidate) > budget_chars:
        return payload
    return candidate
