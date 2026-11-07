"""Source snippets preserve import and public-symbol identity across languages.

source: codebase_extractors' documented regex-based language surface.
"""

import pytest

from mcp_server.core.codebase_extractors import (
    IMPORT_EXTRACTORS,
    SYMBOL_EXTRACTORS,
    extract_docstring,
)


@pytest.mark.parametrize(
    ("language", "source", "imports", "symbols"),
    [
        (
            "rust",
            "use std::collections::HashMap;\n"
            "pub async fn fetch(key: String) {}\n"
            "pub struct Client {}\npub enum Status { Ready }\npub trait Store {}\n",
            ["std::collections::HashMap"],
            {
                ("fetch", "function", "key: String"),
                ("Client", "class", ""),
                ("Status", "enum", ""),
                ("Store", "trait", ""),
            },
        ),
        (
            "swift",
            "import Foundation\npublic final class Client {}\n"
            "public struct Request {}\npublic protocol Store {}\n"
            "public enum Status { case ready }\n"
            "    public static func fetch(key: String) {}\n",
            ["Foundation"],
            {
                ("fetch", "function", "key: String"),
                ("Client", "class", ""),
                ("Request", "class", ""),
                ("Store", "protocol", ""),
                ("Status", "enum", ""),
            },
        ),
        (
            "go",
            'import "fmt"\nimport (\n "context"\n alias "example.net/store"\n)\n'
            "func (c Client) Fetch(key string) {}\n"
            "type Client struct {}\ntype Store interface {}\n",
            ["fmt", "context", "example.net/store"],
            {
                ("Fetch", "function", "key string"),
                ("Client", "struct", ""),
                ("Store", "interface", ""),
            },
        ),
    ],
)
def test_language_registry_extracts_source_identity(language, source, imports, symbols):
    extracted_imports = IMPORT_EXTRACTORS[language](source)
    assert [item.module for item in extracted_imports] == imports
    assert all(not item.is_relative for item in extracted_imports)
    assert {
        (item.name, item.kind, item.signature)
        for item in SYMBOL_EXTRACTORS[language](source)
    } == symbols


def test_relative_imports_preserve_module_and_imported_names():
    python = IMPORT_EXTRACTORS["python"]("from .storage import Reader, Writer\n")
    assert [(item.module, item.names, item.is_relative) for item in python] == [
        (".storage", ["Reader", "Writer"], True)
    ]
    js = IMPORT_EXTRACTORS["typescript"](
        "import { Reader } from './storage';\nconst json = require('node:fs');\n"
    )
    assert [(item.module, item.is_relative) for item in js] == [
        ("./storage", True),
        ("node:fs", False),
    ]


@pytest.mark.parametrize(
    ("language", "source", "expected"),
    [
        ("python", "'''Storage API.'''\n", "Storage API."),
        (
            "typescript",
            "/**\n * Storage API.\n * Keeps provenance.\n */\n",
            "Storage API.\nKeeps provenance.",
        ),
        ("python", "#!/usr/bin/env python\n# Storage API.\n", "Storage API."),
        ("rust", "// Storage API.\nfn main() {}\n", "Storage API."),
        ("swift", "import Foundation\n", ""),
    ],
)
def test_module_documentation_retains_content_without_comment_delimiters(
    language, source, expected
):
    assert extract_docstring(source, language) == expected
