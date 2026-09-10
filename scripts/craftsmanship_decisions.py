"""Resolve explicit source decision IDs and verify the reviewed wiki mirror.

source: ADR-0722"""

from __future__ import annotations

import ast
import io
import re
import sys
import tokenize
from pathlib import Path

_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
from mcp_server.infrastructure.wiki_decision_index import decision_index  # noqa: E402
from mcp_server.shared.wiki_decision_ids import parse_decision_id  # noqa: E402
from mcp_server.infrastructure.wiki_decision_mirror import check_mirror  # noqa: E402

_SOURCE = re.compile(r"#\s*source:\s*(.*)")
_DOC_SOURCE = re.compile(r"(?:^|\s)#?\s*source:[ \t]*([^\n]+)")
_DECISION_INTENT = re.compile(r"ADR(?:[-_\s]|[0-9]|$)", re.IGNORECASE)


def _citation_error(citation: str, line: int, index: dict[str, str]) -> str | None:
    if not _DECISION_INTENT.match(citation):
        return None
    identity = citation.strip().split(maxsplit=1)[0]
    if parse_decision_id(identity) is None:
        return f"line {line}: malformed decision ID {identity!r}"
    if identity not in index:
        return f"line {line}: unknown decision ID {identity}"
    return None


def _docstring_sources(source: str) -> list[tuple[str, int]]:
    """Extract source annotations only from Python's actual docstring nodes."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            continue
        docstring = ast.get_docstring(node, clean=False)
        if docstring is None:
            continue
        for match in _DOC_SOURCE.finditer(docstring):
            line = node.body[0].lineno + docstring[: match.start(1)].count("\n")
            found.append((match.group(1), line))
    return found


def check_source_ids(source: str, index: dict[str, str]) -> list[str]:
    """Validate comment and docstring citations; exclude other string literals."""
    errors = []
    try:
        citations = _docstring_sources(source)
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type != tokenize.COMMENT:
                continue
            match = _SOURCE.match(token.string)
            if match:
                citations.append((match.group(1), token.start[0]))
        for citation, line in citations:
            error = _citation_error(citation, line, index)
            if error:
                errors.append(error)
    except (SyntaxError, tokenize.TokenError, IndentationError) as exc:
        errors.append(f"cannot parse source annotations: {exc}")
    return errors


def check_decisions(project_root: Path, paths: list[str]) -> list[str]:
    """Check selected source files against the complete, unambiguous wiki index."""
    try:
        index = decision_index(project_root / "wiki")
        errors = []
        for relative in sorted(set(paths)):
            path = project_root / relative
            if path.is_file():
                errors.extend(
                    f"{relative}: {error}"
                    for error in check_source_ids(
                        path.read_text(encoding="utf-8"), index
                    )
                )
        if (project_root / "wiki").exists():
            errors.extend(check_mirror(project_root))
        return errors
    except (OSError, ValueError) as exc:
        return [f"decision integrity: {exc}"]
