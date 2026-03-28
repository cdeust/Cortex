"""Type-reference resolution for cross-file linking.

For languages like Swift where files in the same module reference each
other's types without explicit imports. Scans file content for type name
usage and creates file→file edges.

Pure business logic — no I/O.
"""

from __future__ import annotations

import re

from mcp_server.core.codebase_parser import FileAnalysis

# Types too generic to be meaningful cross-file references
_NOISE_TYPES = frozenset({
    "Self", "self", "Any", "String", "Int", "Bool", "Double", "Float",
    "Array", "Dictionary", "Set", "Optional", "Result", "Error", "Void",
    "View", "Body", "some", "Type", "Data", "URL", "Date", "UUID",
    "True", "False", "None", "nil", "List", "Dict", "Tuple",
    "object", "str", "int", "float", "bool", "bytes", "dict", "list",
    "tuple", "set", "type", "cls", "args", "kwargs",
})

_TYPE_KINDS = frozenset({
    "class", "protocol", "enum", "interface", "trait", "struct", "type",
})

MIN_TYPE_NAME_LENGTH = 3


def build_type_index(
    analyses: list[FileAnalysis],
) -> dict[str, str]:
    """Map exported type names to their defining file.

    Only includes class/struct/protocol/enum/interface/trait — not
    functions or methods, which would produce too much noise.

    Returns:
        Dict mapping type_name to defining file path.
    """
    index: dict[str, str] = {}
    for analysis in analyses:
        for sym in analysis.definitions:
            if sym.kind not in _TYPE_KINDS:
                continue
            base = sym.name.split(".")[-1]
            if base in _NOISE_TYPES or len(base) < MIN_TYPE_NAME_LENGTH:
                continue
            index.setdefault(base, analysis.path)
    return index


def resolve_type_references(
    analyses: list[FileAnalysis],
    file_contents: dict[str, str],
) -> list[tuple[str, str]]:
    """Resolve cross-file edges by scanning for type name usage.

    For languages like Swift where files in the same module reference
    each other's types without explicit imports.

    Args:
        analyses: All parsed file analyses.
        file_contents: Map of file_path to raw file text.

    Returns:
        List of (using_file, defining_file) tuples.
    """
    type_index = build_type_index(analyses)
    edges: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    for analysis in analyses:
        content = file_contents.get(analysis.path, "")
        if not content:
            continue
        for type_name, def_file in type_index.items():
            if def_file == analysis.path:
                continue
            if re.search(rf"\b{re.escape(type_name)}\b", content):
                edge = (analysis.path, def_file)
                if edge not in seen:
                    edges.append(edge)
                    seen.add(edge)

    return edges
