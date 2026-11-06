"""Selective comment migration preserves syntax, docstrings and unselected text."""

import ast
import json

import pytest

from scripts.migrate_decision_blocks import apply_selected, inventory


def block(label="rationale"):
    return "".join(f"# {label} evidence {i}\n" for i in range(25))


def apply(tmp_path, source, **kwargs):
    # Byte-exact: apply_selected reads the file's bytes, and the block id is a
    # hash of them. write_text would translate "\n" to "\r\n" on Windows, so
    # the id taken from `source` would name no block of the file (#692).
    (tmp_path / "module.py").write_bytes(source.encode("utf-8"))
    chosen = inventory(source)[0]
    return apply_selected(
        tmp_path,
        "module.py",
        chosen.block_id,
        "ADR-0057",
        "A decision",
        "decision",
        **kwargs,
    )


def test_inventory_requires_long_contiguous_decision_comments():
    source = block("usage") + "x = 1\n" + block() + "y = 2\n"
    items = inventory(source)
    assert len(items) == 1
    assert (items[0].start, items[0].end) == (27, 51)
    assert inventory(block().replace("# rationale evidence 12\n", "\n")) == []
    assert inventory('text = """\n' + block() + '"""\n') == []


def test_extraction_preserves_ast_and_verbatim_evidence(tmp_path):
    (tmp_path / "wiki").mkdir()
    (tmp_path / "wiki" / "manifest.json").write_text(
        json.dumps({"version": 1, "project": "fixture", "pages": {}})
    )
    source = '"""Public module docs."""\n' + block() + "x = 17\n"
    result = apply(tmp_path, source)
    changed = (tmp_path / "module.py").read_text()
    assert ast.dump(ast.parse(source)) == ast.dump(ast.parse(changed))
    assert changed == '"""Public module docs."""\n# source: ADR-0057\nx = 17\n'
    assert result["removed_lines"] == 24
    page = (tmp_path / result["page"]).read_text()
    assert "rationale evidence 24" in page
    assert inventory(source)[0].block_id in page


def test_runtime_docstring_inventory_is_not_extractable(tmp_path):
    source = (
        '"""\n' + "\n".join(f"rationale evidence {i}" for i in range(25)) + '\n"""\n'
    )
    assert inventory(source)[0].status == "unsupported-runtime-docstring"
    with pytest.raises(ValueError, match="runtime-docstring"):
        apply(tmp_path, source)
    assert (tmp_path / "module.py").read_text() == source
    assert not (tmp_path / "wiki").exists()


@pytest.mark.parametrize(
    "directive",
    ["# fmt: off", "# coding: utf-8", "# pragma: no cover", "#!/usr/bin/python3"],
)
def test_operational_directives_are_never_extracted(tmp_path, directive):
    source = directive + "\n" + block()
    with pytest.raises(ValueError, match="operational-directive"):
        apply(tmp_path, source)


def test_stale_or_ambiguous_selection_fails_without_writes(tmp_path):
    original = block()
    (tmp_path / "module.py").write_text(original + "x = 1\n" + original)
    with pytest.raises(ValueError, match="exactly one unchanged"):
        apply_selected(
            tmp_path,
            "module.py",
            inventory(original)[0].block_id,
            "ADR-0057",
            "A decision",
            "decision",
        )
    assert not (tmp_path / "wiki").exists()
    (tmp_path / "module.py").write_text(
        original.replace("evidence 0", "corrected evidence 0")
    )
    with pytest.raises(ValueError, match="exactly one unchanged"):
        apply_selected(
            tmp_path,
            "module.py",
            inventory(original)[0].block_id,
            "ADR-0057",
            "A decision",
            "decision",
        )


def test_duplicate_identity_is_not_overwritten(tmp_path):
    directory = tmp_path / "wiki" / "adr"
    directory.mkdir(parents=True)
    existing = directory / "0057-existing.md"
    existing.write_text("prior evidence")
    with pytest.raises(ValueError, match="already exists"):
        apply(tmp_path, block())
    assert existing.read_text() == "prior evidence"
    assert (tmp_path / "module.py").read_text() == block()


def test_source_escape_rejected_before_mutation(tmp_path):
    with pytest.raises(ValueError, match="inside the project"):
        apply_selected(
            tmp_path, "../module.py", "stale", "ADR-0057", "A decision", "decision"
        )
    assert not (tmp_path / "wiki").exists()


def test_failed_mirror_generation_rolls_back_exact_files(tmp_path, monkeypatch):
    from scripts import decision_migration_io as migration_io

    (tmp_path / "wiki").mkdir()
    manifest = json.dumps({"version": 1, "project": "fixture", "pages": {}})
    (tmp_path / "wiki" / "manifest.json").write_text(manifest)

    real_generate = migration_io.generate_mirror

    def fail(root):
        real_generate(root)
        raise OSError("simulated write failure")

    monkeypatch.setattr(migration_io, "generate_mirror", fail)
    with pytest.raises(OSError, match="simulated"):
        apply(tmp_path, block())
    assert (tmp_path / "module.py").read_text() == block()
    assert (tmp_path / "wiki" / "manifest.json").read_text() == manifest
    assert not (tmp_path / "wiki" / "adr" / "0057-decision.md").exists()
    assert not (tmp_path / "wiki" / ".generated" / "decision-index.json").exists()
    assert not (tmp_path / "wiki" / ".generated" / "decision-index-state.json").exists()
    assert not (tmp_path / "docs" / "adr" / "ADR-0057-decision.md").exists()


def test_crlf_source_keeps_line_endings_and_content_address(tmp_path):
    (tmp_path / "wiki").mkdir()
    (tmp_path / "wiki" / "manifest.json").write_text(
        json.dumps({"version": 1, "project": "fixture", "pages": {}})
    )
    source = (block() + "x = 17\n").replace("\n", "\r\n")
    (tmp_path / "module.py").write_bytes(source.encode())
    apply_selected(
        tmp_path,
        "module.py",
        inventory(source)[0].block_id,
        "ADR-0057",
        "A decision",
        "decision",
    )
    assert (tmp_path / "module.py").read_bytes() == b"# source: ADR-0057\r\nx = 17\r\n"


def existing_index(root):
    from mcp_server.infrastructure.project_wiki import register_project_page
    from mcp_server.infrastructure.wiki_decision_index import write_decision_index
    from mcp_server.infrastructure.wiki_decision_mirror import generate_mirror

    (root / "wiki" / "adr").mkdir(parents=True)
    (root / "wiki" / "manifest.json").write_text(
        json.dumps({"version": 1, "project": "fixture", "pages": {}})
    )
    (root / "wiki" / "adr" / "0056-original.md").write_text("Original decision")
    register_project_page(root, "adr/0056-original.md")
    generate_mirror(root)
    write_decision_index(root / "wiki")


def test_failed_migration_keeps_existing_exact_lookup_usable(tmp_path, monkeypatch):
    from mcp_server.infrastructure.wiki_decision_index import lookup_decision
    from scripts import decision_migration_io as migration_io

    existing_index(tmp_path)
    wiki = tmp_path / "wiki"
    original_map = (wiki / ".generated" / "decision-index.json").read_bytes()
    assert lookup_decision(wiki, "ADR-0056") == "adr/0056-original.md"
    real_generate = migration_io.generate_mirror

    def fail(root):
        real_generate(root)
        raise OSError("initial mirror failure")

    monkeypatch.setattr(migration_io, "generate_mirror", fail)
    with pytest.raises(OSError, match="initial mirror failure"):
        apply(tmp_path, block())
    assert lookup_decision(wiki, "ADR-0056") == "adr/0056-original.md"
    assert lookup_decision(wiki, "ADR-0057") is None
    assert (wiki / ".generated" / "decision-index.json").read_bytes() == original_map
    assert (tmp_path / "module.py").read_text() == block()


def test_rollback_failure_is_explicit_without_losing_original_exception(
    tmp_path, monkeypatch
):
    from scripts import decision_migration_io as migration_io

    existing_index(tmp_path)
    real_write = migration_io.write_decision_index
    calls = []

    def write(root):
        calls.append(root)
        if len(calls) > 1:
            raise OSError("refresh unavailable")
        return real_write(root)

    def fail(root):
        raise OSError("initial mirror failure")

    monkeypatch.setattr(migration_io, "write_decision_index", write)
    monkeypatch.setattr(migration_io, "generate_mirror", fail)
    with pytest.raises(OSError, match="initial mirror failure") as error:
        apply(tmp_path, block())
    assert "Migration rollback incomplete" in str(error.value.__cause__)
    assert "refresh unavailable" in str(error.value.__cause__)
    assert (tmp_path / "module.py").read_text() == block()
