"""Synthetic adversaries for W3-3; no private corpus or model required."""

from __future__ import annotations

# source: ADR-0735
FIXTURE_CHARS = 10_000


def repeat_to_length(unit: str, size: int = FIXTURE_CHARS) -> str:
    return (unit * (size // len(unit) + 1))[:size]


def fixtures(word_limit: int) -> dict[str, str]:
    """The WordPiece word limit is read from the supplied tokenizer config."""
    middle = FIXTURE_CHARS - len("ab")
    return {
        "internal_spaces": "a" + " " * middle + "b",
        "leading_spaces": " " * (FIXTURE_CHARS - len("b")) + "b",
        "internal_tabs": "a" + "\t" * middle + "b",
        "internal_nbsp": "a" + "\u00a0" * middle + "b",
        "null_controls": "a" + "\x00" * middle + "b",
        "format_controls": "a" + "\u200d" * middle + "b",
        "replacement_chars": "a" + "\ufffd" * middle + "b",
        "combining_marks": "a" + "\u0301" * middle + "b",
        "composed_accents": repeat_to_length("École déjà vu. "),
        "decomposed_accents": repeat_to_length("E\u0301cole de\u0301ja\u0300 vu. "),
        "joined_emoji": repeat_to_length("👨\u200d👩\u200d👧\u200d👦 says hi. "),
        "long_word": "a" * FIXTURE_CHARS,
        "word_limit_boundary": ("a" * (word_limit + 1)).ljust(FIXTURE_CHARS),
        "chinese_punctuation": repeat_to_length("你好，世界。 "),
        "added_special_tokens": repeat_to_length("a [MASK] [CLS] [SEP] b "),
        "ordinary_prose": repeat_to_length("The memory stores complete source text. "),
    }
