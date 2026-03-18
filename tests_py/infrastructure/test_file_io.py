"""Tests for mcp_server.infrastructure.file_io — ported from file-io.test.js."""

import json

from mcp_server.infrastructure.file_io import (
    read_json,
    write_json,
    read_text_file,
    ensure_dir,
    list_dir,
)


class TestReadJSON:
    def test_parses_valid_json(self, tmp_path):
        p = tmp_path / "valid.json"
        p.write_text(json.dumps({"foo": 42}), encoding="utf-8")
        assert read_json(p) == {"foo": 42}

    def test_returns_none_for_missing(self, tmp_path):
        assert read_json(tmp_path / "nonexistent.json") is None

    def test_returns_none_for_corrupt(self, tmp_path):
        p = tmp_path / "corrupt.json"
        p.write_text("{not valid json!!!", encoding="utf-8")
        assert read_json(p) is None


class TestWriteJSON:
    def test_creates_parent_dirs(self, tmp_path):
        p = tmp_path / "nested" / "deep" / "out.json"
        write_json(p, {"hello": "world"})
        assert p.exists()
        assert json.loads(p.read_text(encoding="utf-8")) == {"hello": "world"}

    def test_overwrites_existing(self, tmp_path):
        p = tmp_path / "overwrite.json"
        write_json(p, {"v": 1})
        write_json(p, {"v": 2})
        assert json.loads(p.read_text(encoding="utf-8"))["v"] == 2


class TestEnsureDir:
    def test_creates_nested(self, tmp_path):
        d = tmp_path / "a" / "b" / "c"
        ensure_dir(d)
        assert d.exists()
        assert d.is_dir()

    def test_no_error_if_exists(self, tmp_path):
        d = tmp_path / "already"
        d.mkdir()
        ensure_dir(d)  # should not throw


class TestReadTextFile:
    def test_reads_utf8(self, tmp_path):
        p = tmp_path / "hello.txt"
        p.write_text("hello world", encoding="utf-8")
        assert read_text_file(p) == "hello world"

    def test_returns_none_for_missing(self, tmp_path):
        assert read_text_file(tmp_path / "missing.txt") is None


class TestListDir:
    def test_lists_files(self, tmp_path):
        d = tmp_path / "listdir-test"
        d.mkdir()
        (d / "a.txt").write_text("a")
        (d / "b.txt").write_text("b")
        result = list_dir(d)
        assert isinstance(result, list)
        assert "a.txt" in result
        assert "b.txt" in result

    def test_returns_none_for_missing(self, tmp_path):
        assert list_dir(tmp_path / "no-such-dir") is None
