"""Kills the surviving mutants a scoped mutmut run (issue #265) reported
against `sqlite_sql_translate.py`'s `_translate_sql`/`_returning_was_stripped`.

Every surviving mutant drops (or alters) a `flags=re.IGNORECASE` argument on
one of the module's `re.sub`/`re.search` calls. Two shapes, both surfaced by
the issue's 20 named mutant ids (`mutmut_8`, `_10`, `_38`, `_51`, `_62`,
`_64`, `_78`, `_92`, `_105`, `_117`, `_119`, `_134`, `_136`, `_137`, `_149`,
`_161`, `_163`, `_175`, `_186`, `_188`):

1. **Real gap (6 ids: 8, 62, 117, 134, 161, 186)** — the mutant *removes*
   `re.IGNORECASE` outright. Every fixture in the sibling
   `test_wiki_pipeline_sqlite.py` case-insensitivity suite happens to use an
   input whose case already matches the pattern's literal spelling, so the
   assertion passes whether or not the flag fires. A test that instead
   supplies the OPPOSITE case is the only way to make the flag's presence
   observable — that is what each test below does.
2. **Equivalent mutant (14 ids: 10, 38, 51, 64, 78, 92, 105, 119, 136, 137,
   149, 163, 175, 188)** — the mutant only *re-spells* the pattern's own
   literal case (e.g. `SERIAL` -> `serial`) while leaving `re.IGNORECASE` in
   place. Under that flag, a character's case inside the pattern is provably
   irrelevant to what it matches (Python `re` docs, "IGNORECASE": "Perform
   case-insensitive matching; expressions like [A-Z] will also match
   lowercase letters"). No input, however constructed, can distinguish
   `re.compile(r"SERIAL", re.I)` from `re.compile(r"serial", re.I)` —
   confirmed empirically (`python3 -c` diff harness, run against every one of
   the 14 ids, all identical for uppercase/lowercase/mixed-case probes) for
   `serial`/`timestamptz`/`now()`/`update...set`/`any(`/the entity-ids
   character class/`xmax` (both the keyword and the `AS`/`as` join
   keyword)/`is distinct from`/`returning`/`wiki.`/`array_length` — the
   char-class variants (`[a-z_]` vs `[A-Z_]`) included, since IGNORECASE
   folds them identically for every character. No test can be written that
   distinguishes these 14 mutants from the original code, so they are
   permanent, documented non-blocking survivors (coding-standards.md
   §12.1(b)).
"""

from __future__ import annotations

import mcp_server.infrastructure.sqlite_sql_translate as sqltr
from mcp_server.infrastructure.sqlite_sql_translate import (
    _returning_was_stripped,
    _translate_sql,
)

_NOW = "strftime('%Y-%m-%dT%H:%M:%fZ', 'now')"


def test_returning_was_stripped_matches_lowercase_returning(monkeypatch):
    """Kills mutmut_8 (drops IGNORECASE from `_returning_was_stripped`'s regex).

    On this runtime `_SUPPORTS_RETURNING` is True, so `_returning_was_stripped`
    returns False regardless of whether the regex matches at all — the `and`
    short-circuits on `not _SUPPORTS_RETURNING`. Patching the flag False is
    required to make the regex's own match result observable.
    """
    monkeypatch.setattr(sqltr, "_SUPPORTS_RETURNING", False)
    assert _returning_was_stripped("insert into t (a) values (1) returning id") is True


def test_translate_sql_default_now_lowercase_still_translates():
    """Kills mutmut_62 (drops IGNORECASE from the `DEFAULT NOW()` rule).

    Every existing DEFAULT-NOW fixture supplies uppercase input, so dropping
    the flag never showed up there.
    """
    assert _translate_sql("create table t (ts timestamptz default now())") == (
        f"create table t (ts TEXT DEFAULT ({_NOW}))"
    )


def test_translate_sql_array_overlap_matches_uppercase_column():
    """Kills mutmut_117 (drops IGNORECASE from the `&&` array-overlap rule).

    The rule's pattern restricts the captured identifier to `[a-z_]`
    lexically; only `re.IGNORECASE` makes it also match an uppercase column
    name. Without the flag `ENTITY_IDS && ?` is left untranslated.
    """
    assert _translate_sql("WHERE ENTITY_IDS && ?") == (
        "WHERE EXISTS (SELECT 1 FROM json_each(ENTITY_IDS) AS _ovl_l "
        "JOIN json_each(?) AS _ovl_r ON _ovl_l.value = _ovl_r.value)"
    )


def test_translate_sql_xmax_drop_matches_uppercase_and_lowercase_as():
    """Kills mutmut_134 (drops IGNORECASE from the `xmax` drop rule).

    Covers both axes the flag protects: the `XMAX` literal and the `as`
    keyword, either of which fails to match case-sensitively.
    """
    assert _translate_sql(", (XMAX = 0) AS inserted") == ""
    assert _translate_sql(", (xmax = 0) as inserted") == ""


def test_translate_sql_strips_lowercase_returning_when_unsupported(monkeypatch):
    """Kills mutmut_161 (drops IGNORECASE from the RETURNING-strip rule
    inside `_translate_sql`, distinct from `_returning_was_stripped`'s own
    regex covered by mutmut_8/10 above).
    """
    monkeypatch.setattr(sqltr, "_SUPPORTS_RETURNING", False)
    assert (
        _translate_sql("insert into wiki.pages (slug) values (%s) returning id")
        == "insert into wiki_pages (slug) values (?) "
    )


def test_translate_sql_array_length_matches_uppercase():
    """Kills mutmut_186 (drops IGNORECASE from the `array_length` rule)."""
    assert _translate_sql("SELECT array_length(ENTITY_IDS, 1)") == (
        "SELECT json_array_length(ENTITY_IDS)"
    )
