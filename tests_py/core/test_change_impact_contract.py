"""ADR-0121: code-change notifications retain deterministic evidence matches."""

from mcp_server.core.change_impact_matcher import match_memories


def test_symbol_tails_paths_and_tags_contribute_distinct_evidence():
    memories = [
        {"memory_id": 4, "content": "Parser.PARSE validates config.py", "tags": []},
        {"id": 2, "content": None, "tags": ["CONFIG.PY"]},
        {"memory_id": 3, "content": "docs/guide.md explains parse()"},
        {"content": "parse() without an identity must not be returned"},
        {"id": 5, "content": "unrelated", "tags": []},
    ]
    result = match_memories(
        impacted_symbols=["pkg.Parser.parse", ""],
        impacted_files=["src/config.py", "docs/guide.md", ""],
        memories=memories,
    )
    assert [r.memory_id for r in result] == [3, 4, 2]
    assert result[0].matched_symbols == ["pkg.Parser.parse"]
    assert result[0].matched_files == ["docs/guide.md"]
    assert result[1].match_count == 2
    assert result[2].matched_files == ["src/config.py"]


def test_windows_basename_and_custom_identity_are_supported():
    result = match_memories(
        impacted_symbols=["reload"],
        impacted_files=[r"C:\project\config.py"],
        memories=[{"key": "record", "content": "reload", "tags": ["config.py"]}],
        id_key="key",
    )
    assert result[0].memory_id == "record" and result[0].match_count == 2
    assert match_memories(impacted_symbols=[], impacted_files=[], memories=[]) == []
