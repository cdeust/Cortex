"""Inventory long decision comments; extract only an explicitly reviewed block.

source: ADR-0769"""

from __future__ import annotations

import argparse
import ast
import hashlib
import io
import json
import re
import sys
import tokenize
from dataclasses import asdict, dataclass
from pathlib import Path

_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
from mcp_server.infrastructure.wiki_decision_index import decision_index  # noqa: E402
from mcp_server.shared.wiki_decision_ids import parse_decision_id  # noqa: E402
from scripts.decision_migration_io import persist_extraction  # noqa: E402

# source: ADR-0769
MIN_BLOCK_LINES = 25
_DECISION = re.compile(
    r"\b(decision|rationale|rejected|trade-?off|why)\b", re.IGNORECASE
)
_OPERATIONAL = re.compile(
    r"(?:\b(?:noqa|type:\s*ignore|fmt:\s*(?:off|on))\b|coding[:=]|pragma:|^#!)"
)
_SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


@dataclass(frozen=True)
class Candidate:
    """Content-addressed selection; line numbers are for human review only."""

    block_id: str
    start: int
    end: int
    kind: str
    status: str
    text: str


def _candidate(lines: list[str], start: int, end: int, kind: str) -> Candidate | None:
    text = "".join(lines[start - 1 : end])
    if end - start + 1 < MIN_BLOCK_LINES or not _DECISION.search(text):
        return None
    status = "selectable" if kind == "comment" else "unsupported-runtime-docstring"
    if kind == "comment" and _OPERATIONAL.search(text):
        status = "unsupported-operational-directive"
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return Candidate(digest, start, end, kind, status, text)


def _comment_ranges(source: str) -> list[tuple[int, int]]:
    lines = source.splitlines(keepends=True)
    rows = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.COMMENT:
            row, column = token.start
            if not lines[row - 1][:column].strip():
                rows.append(row)
    ranges = []
    for row in rows:
        if ranges and row == ranges[-1][1] + 1:
            ranges[-1] = (ranges[-1][0], row)
        else:
            ranges.append((row, row))
    return ranges


def inventory(source: str) -> list[Candidate]:
    """Only contiguous full-line comments or real docstrings with decision cues."""
    tree = ast.parse(source)
    lines = source.splitlines(keepends=True)
    ranges = [(start, end, "comment") for start, end in _comment_ranges(source)]
    for node in ast.walk(tree):
        if isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            if ast.get_docstring(node) is not None:
                first = node.body[0]
                ranges.append(
                    (first.lineno, first.end_lineno or first.lineno, "docstring")
                )
    candidates = [_candidate(lines, start, end, kind) for start, end, kind in ranges]
    return sorted(
        (item for item in candidates if item is not None), key=lambda c: c.start
    )


def _source_path(project_root: Path, relative: str) -> Path:
    path = project_root / relative
    if Path(relative).is_absolute() or not path.resolve().is_relative_to(
        project_root.resolve()
    ):
        raise ValueError("source file must stay inside the project")
    if path.suffix != ".py" or path.is_symlink():
        raise ValueError("only regular Python source files can be migrated")
    return path


def _selected(source: str, block_id: str) -> Candidate:
    matches = [item for item in inventory(source) if item.block_id == block_id]
    if len(matches) != 1:
        raise ValueError("selection must identify exactly one unchanged candidate")
    chosen = matches[0]
    if chosen.status != "selectable":
        raise ValueError(f"cannot extract {chosen.status}")
    return chosen


def _replacement(source: str, chosen: Candidate, identity: str) -> str:
    lines = source.splitlines(keepends=True)
    original = lines[chosen.start - 1]
    indent = original[: len(original) - len(original.lstrip())]
    ending = "\r\n" if original.endswith("\r\n") else "\n"
    lines[chosen.start - 1 : chosen.end] = [f"{indent}# source: {identity}{ending}"]
    result = "".join(lines)
    if ast.dump(ast.parse(source)) != ast.dump(ast.parse(result)):
        raise ValueError("extraction would change the Python AST")
    return result


def _page(chosen: Candidate, relative: str, identity: str, title: str) -> str:
    body = "\n".join(re.sub(r"^\s*# ?", "", line) for line in chosen.text.splitlines())
    return (
        "---\nkind: decision\nstatus: accepted\n"
        f"decision_id: {identity}\ntitle: {json.dumps(title)}\n---\n\n"
        f"# {identity}: {title}\n\n"
        f"Extracted from `{relative}`, original lines {chosen.start}–{chosen.end}.\n"
        f"Original comment SHA-256: `{chosen.block_id}`.\n\n{body}\n"
    )


def _validate_metadata(identity: str, title: str, slug: str) -> None:
    if parse_decision_id(identity) is None or _SLUG.fullmatch(slug) is None:
        raise ValueError(
            "a canonical ADR-NNNN ID and lowercase filename slug are required"
        )
    if not title.strip() or "\n" in title or "\r" in title:
        raise ValueError("title must be a nonempty single line")


def apply_selected(
    project_root: Path,
    relative: str,
    block_id: str,
    identity: str,
    title: str,
    slug: str,
) -> dict[str, object]:
    """Create a canonical page and pointer, with no live wiki/database writes."""
    _validate_metadata(identity, title, slug)
    if identity in decision_index(project_root / "wiki"):
        raise ValueError(f"decision already exists: {identity}")
    source_path = _source_path(project_root, relative)
    source = source_path.read_bytes().decode("utf-8")
    chosen = _selected(source, block_id)
    updated = _replacement(source, chosen, identity)
    page = project_root / "wiki" / "adr" / f"{identity[4:]}-{slug}.md"
    if not page.resolve().is_relative_to(project_root.resolve()):
        raise ValueError("canonical page must stay inside the project")
    persist_extraction(
        project_root,
        relative,
        updated.encode("utf-8"),
        page.relative_to(project_root).as_posix(),
        _page(chosen, relative, identity, title),
    )
    return {
        "source": relative,
        "decision": identity,
        "page": page.relative_to(project_root).as_posix(),
        "removed_lines": chosen.end - chosen.start,
        "ast_unchanged": True,
        "next_action": (
            "Review the canonical page, generated mirror and source pointer "
            "before committing."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", help="explicit Python source paths")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--apply", metavar="BLOCK_SHA256")
    parser.add_argument("--decision-id")
    parser.add_argument("--title")
    parser.add_argument("--slug")
    args = parser.parse_args(argv)
    if args.apply:
        if len(args.files) != 1 or not all((args.decision_id, args.title, args.slug)):
            parser.error("--apply requires one file, --decision-id, --title and --slug")
        result = apply_selected(
            args.root,
            args.files[0],
            args.apply,
            args.decision_id,
            args.title,
            args.slug,
        )
    else:
        result = {
            relative: [
                asdict(item)
                for item in inventory(
                    _source_path(args.root, relative).read_bytes().decode("utf-8")
                )
            ]
            for relative in args.files
        }
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
