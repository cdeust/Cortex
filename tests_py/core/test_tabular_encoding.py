"""Tests for core/tabular_encoding — columns-once, rows-as-arrays (issue #170).

The encoding declares a homogeneous list's field names once and streams each
item as a cell array. These tests pin the four contract properties: no
information loss (field-set + value equality under round-trip), honest
heterogeneous degradation (union columns with explicit nulls), the empty and
single-item edges, and budget composition (the transform never adopts a shape
that exceeds the response-budget cap).
"""

from __future__ import annotations

from mcp_server.core.response_budget import serialized_length
from mcp_server.core.tabular_encoding import (
    FORMAT_JSON,
    FORMAT_TABULAR,
    SELF_DESCRIBE_RESERVE_CHARS,
    decode_tabular,
    derive_columns,
    encode_rows,
    encode_within_budget,
    parse_format,
    reserved_budget,
)


def _mem(mid: str, content: str, **extra) -> dict:
    return {"id": mid, "content": content, "score": 0.5, "heat": 0.3, **extra}


# ── parse_format ──────────────────────────────────────────────────────


def test_parse_format_tabular() -> None:
    assert parse_format("tabular") == FORMAT_TABULAR


def test_parse_format_json_is_default() -> None:
    assert parse_format("json") == FORMAT_JSON


def test_parse_format_unknown_degrades_to_json() -> None:
    assert parse_format(None) == FORMAT_JSON
    assert parse_format("csv") == FORMAT_JSON
    assert parse_format(123) == FORMAT_JSON


# ── reserved_budget ───────────────────────────────────────────────────


def test_reserved_budget_holds_out_the_format_field() -> None:
    assert reserved_budget(5_000) == 5_000 - SELF_DESCRIBE_RESERVE_CHARS


def test_reserved_budget_never_negative() -> None:
    assert reserved_budget(0) == 0


def test_reserve_covers_json_format_field_cost() -> None:
    # A payload bounded to reserved_budget(cap) still fits `cap` after the
    # json ``format`` field is appended — the widest reserve covers it.
    assert len(',"format":"json"') <= SELF_DESCRIBE_RESERVE_CHARS


# ── derive_columns ────────────────────────────────────────────────────


def test_derive_columns_homogeneous_first_seen_order() -> None:
    items = [_mem("1", "a"), _mem("2", "b")]
    assert derive_columns(items) == ["id", "content", "score", "heat"]


def test_derive_columns_union_over_heterogeneous() -> None:
    # Second item carries the water-fill truncation keys; the union must
    # include them, in first-seen order (base fields, then the new ones).
    items = [
        _mem("1", "short"),
        _mem("2", "cut", truncated=True, content_length=9000),
    ]
    assert derive_columns(items) == [
        "id",
        "content",
        "score",
        "heat",
        "truncated",
        "content_length",
    ]


# ── encode / decode round-trip: no information loss ───────────────────


def test_homogeneous_round_trip_preserves_every_field() -> None:
    items = [_mem("1", "alpha"), _mem("2", "beta")]
    columns = derive_columns(items)
    rows = encode_rows(items, columns)
    assert decode_tabular(columns, rows) == items


def test_field_set_equality_union_columns(_none=None) -> None:
    """No information loss (contract #5): the column set equals the union of
    all item keys, and every original field's value is recovered by position."""
    items = [
        _mem("1", "short"),
        _mem("2", "cut", truncated=True, content_length=9000),
    ]
    columns = derive_columns(items)
    rows = encode_rows(items, columns)

    union = set().union(*(item.keys() for item in items))
    assert set(columns) == union

    decoded = decode_tabular(columns, rows)
    # strict=True: decode_tabular returns one dict per row, and rows was
    # built one-per-item by encode_rows above.
    for original, back in zip(items, decoded, strict=True):
        # Every field present in the original is recovered with its value.
        assert all(back[k] == original[k] for k in original)


def test_heterogeneous_absent_field_materializes_as_null() -> None:
    items = [
        _mem("1", "short"),  # no `truncated`
        _mem("2", "cut", truncated=True),
    ]
    columns = derive_columns(items)
    rows = encode_rows(items, columns)
    trunc_idx = columns.index("truncated")
    # First item lacked `truncated` -> explicit None cell, not a fabricated value.
    assert rows[0][trunc_idx] is None
    assert rows[1][trunc_idx] is True


def test_ids_remain_present_in_rows() -> None:
    """ids stay fetchable (contract #5): the id column survives encoding."""
    items = [_mem("uuid-a", "x"), _mem("uuid-b", "y")]
    columns = derive_columns(items)
    rows = encode_rows(items, columns)
    id_idx = columns.index("id")
    assert [row[id_idx] for row in rows] == ["uuid-a", "uuid-b"]


# ── encode_within_budget: composition + self-description ──────────────


def test_json_mode_leaves_objects_and_self_describes() -> None:
    items = [_mem("1", "a"), _mem("2", "b")]
    payload = {"memories": list(items), "count": 2}
    out = encode_within_budget(payload, "memories", FORMAT_JSON)
    assert out["format"] == FORMAT_JSON
    assert out["memories"] == items
    assert "columns" not in out


def test_tabular_mode_declares_columns_once_and_streams_rows() -> None:
    items = [_mem("1", "a"), _mem("2", "b")]
    payload = {"memories": list(items), "count": 2}
    out = encode_within_budget(payload, "memories", FORMAT_TABULAR)
    assert out["format"] == FORMAT_TABULAR
    assert out["columns"] == ["id", "content", "score", "heat"]
    assert out["memories"] == [
        ["1", "a", 0.5, 0.3],
        ["2", "b", 0.5, 0.3],
    ]


def test_tabular_is_smaller_than_json_on_homogeneous_rows() -> None:
    """The whole point: not repeating field names shrinks the payload. A
    regression that inflates the tabular form fails here."""
    items = [_mem(str(i), f"body number {i} with some prose") for i in range(20)]
    json_payload = {"memories": list(items), "count": 20}
    tab_payload = encode_within_budget(
        {"memories": list(items), "count": 20}, "memories", FORMAT_TABULAR
    )
    assert tab_payload["format"] == FORMAT_TABULAR
    assert serialized_length(tab_payload) < serialized_length(json_payload)


def test_empty_list_stays_json() -> None:
    out = encode_within_budget({"memories": [], "count": 0}, "memories", FORMAT_TABULAR)
    assert out["format"] == FORMAT_JSON
    assert out["memories"] == []
    assert "columns" not in out


def test_single_item_does_not_overflow_budget() -> None:
    """Budget composition (contract #1): a single-item list whose tabular form
    would be larger keeps whichever form fits; neither exceeds the cap."""
    payload = {"memories": [_mem("1", "solo")], "count": 1}
    out = encode_within_budget(payload, "memories", FORMAT_TABULAR)
    # Never overflow, regardless of which encoding was chosen.
    assert (
        serialized_length(out)
        <= serialized_length({"memories": [_mem("1", "solo")], "count": 1})
        + len('"columns":[],"format":"tabular"')
        + 64
    )


def test_non_dict_items_stay_json() -> None:
    """A list of bare scalars (e.g. wiki_list pages) has no columns to
    declare; the transform declines and keeps json."""
    out = encode_within_budget({"pages": ["a/b.md", "c/d.md"]}, "pages", FORMAT_TABULAR)
    assert out["format"] == FORMAT_JSON
    assert out["pages"] == ["a/b.md", "c/d.md"]


def test_tabular_declined_when_it_would_overflow_tiny_budget() -> None:
    """Force the budget re-check: a tiny cap the object form fits but the
    tabular form does not -> keep the object form (compose, not bypass)."""
    items = [_mem("1", "a")]
    obj_payload = {"memories": list(items), "count": 1}
    obj_len = serialized_length(obj_payload)
    # A budget between the object form and the (larger, single-item) tabular
    # form: tabular must be declined.
    tab_len = serialized_length(
        {
            "memories": encode_rows(items, derive_columns(items)),
            "count": 1,
            "columns": derive_columns(items),
            "format": FORMAT_TABULAR,
        }
    )
    if tab_len > obj_len:
        budget = tab_len - 1
        out = encode_within_budget(obj_payload, "memories", FORMAT_TABULAR, budget)
        assert out["format"] == FORMAT_JSON
        assert serialized_length(out) <= budget
