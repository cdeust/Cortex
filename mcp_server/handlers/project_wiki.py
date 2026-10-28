"""Filesystem-only project publication transaction. # source: ADR-0056"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from collections.abc import Callable

from mcp_server.infrastructure.project_wiki import (
    contained_file,
    load_manifest,
    register_project_page,
    resolve_wiki_root,
)
from mcp_server.infrastructure.wiki_decision_index import write_decision_index
from mcp_server.infrastructure.wiki_decision_mirror import generate_mirror
from mcp_server.infrastructure.wiki_pages_listing import next_adr_number
from mcp_server.infrastructure.wiki_store import write_page
from mcp_server.shared.log_file_lock import log_file_lock
from mcp_server.shared.wiki_layout import adr_filename, slugify
from mcp_server.shared.wiki_pages import build_adr
from mcp_server.shared import gated_files


def _snapshot(project: Path, page: Path) -> dict[Path, bytes | None]:
    paths = [
        page,
        contained_file(project, "wiki/manifest.json"),
        contained_file(project, "wiki/.generated/INDEX.md"),
    ]
    mirror = contained_file(project, "docs/adr")
    if mirror.exists():
        paths.extend(
            contained_file(project, str(p.relative_to(project)))
            for p in mirror.rglob("*")
            if p.is_file()
        )
    return {path: path.read_bytes() if path.is_file() else None for path in paths}


def _restore(project: Path, before: dict[Path, bytes | None]) -> None:
    mirror = contained_file(project, "docs/adr")
    if mirror.exists():
        for path in mirror.rglob("*"):
            if path.is_file() and path not in before:
                contained_file(project, str(path.relative_to(project))).unlink()
    for path, content in before.items():
        path = contained_file(project, str(path.relative_to(project)))
        if content is None:
            path.unlink(missing_ok=True)
        else:
            gated_files.write_bytes(path, content)
    # Rollback itself changes directory metadata: old freshness stamps are invalid.
    write_decision_index(project / "wiki")


def _publish(project: Path, relative: str, content: str, mode: str) -> dict[str, Any]:
    wiki = resolve_wiki_root(str(project), project / "wiki")
    page = contained_file(wiki, relative)
    if page.suffix != ".md":
        raise ValueError("project wiki pages must end in .md")
    before = _snapshot(project, page)
    try:
        result = write_page(wiki, relative, content, mode=mode)
        if relative.startswith("adr/"):
            manifest = load_manifest(project)
            identifier = "ADR-" + page.name.split("-", 1)[0]
            old = manifest["pages"].get(identifier, {})
            register_project_page(project, relative, old.get("mirror"))
        mirror = generate_mirror(project)
        write_decision_index(wiki)
    except Exception:  # noqa: BLE001 — transaction rollback must cover every failure
        _restore(project, before)
        raise
    return {
        "path": result.path,
        "mode": result.mode,
        "created": result.created,
        "bytes_written": result.bytes_written,
        "root": str(wiki),
        "memory_sync": "project-files-only",
        **mirror,
    }


def write(args: dict[str, Any]) -> dict[str, Any]:
    wiki = resolve_wiki_root(args["project_root"], Path("."))
    project = wiki.parent
    with log_file_lock(wiki / ".adr-allocation"):
        return _publish(
            project,
            str(args["path"]),
            str(args["content"]),
            str(args.get("mode") or "create"),
        )


def adr(args: dict[str, Any]) -> dict[str, Any]:
    wiki = resolve_wiki_root(args["project_root"], Path("."))
    project = wiki.parent
    with log_file_lock(wiki / ".adr-allocation"):
        number = next_adr_number(wiki)
        domain = slugify(load_manifest(project)["project"])
        title = str(args["title"]).strip()
        relative = f"adr/{domain}/{adr_filename(number, slugify(title))}"
        status = str(args.get("status") or "accepted")
        content = build_adr(
            number=number,
            title=title,
            context=str(args["context"]),
            decision=str(args["decision"]),
            consequences=str(args["consequences"]),
            status=status,
            tags=args.get("tags") or [],
        )
        result = _publish(project, relative, content, "create")
        return {**result, "number": number, "title": title, "status": status}


def reindex_project(
    project_root: str, renderer: Callable[[Path], dict[str, Any]]
) -> dict[str, Any]:
    wiki = resolve_wiki_root(project_root, Path("."))
    project = wiki.parent
    with log_file_lock(wiki / ".adr-allocation"):
        before = _snapshot(project, wiki / ".generated/INDEX.md")
        try:
            result = renderer(wiki)
            mirror = generate_mirror(project)
        except Exception:  # noqa: BLE001 — transaction rollback must cover every failure
            _restore(project, before)
            raise
    return {**result, **mirror, "memory_sync": "project-files-only"}
