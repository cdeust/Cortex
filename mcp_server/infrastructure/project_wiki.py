"""source: ADR-0593"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mcp_server.shared.wiki_decision_ids import decision_id, parse_decision_filename


def contained_file(root: Path, relative: str) -> Path:
    path = Path(relative)
    if (
        path.is_absolute()
        or not path.parts
        or any(p in {".", ".."} for p in path.parts)
    ):
        raise ValueError(f"invalid project wiki path: {relative!r}")
    base = root.resolve()
    target = root / path
    for parent in (target, *target.parents):
        if parent == root:
            break
        if parent.is_symlink():
            raise ValueError(f"symlink in project wiki path: {relative}")
    if not target.resolve().is_relative_to(base):
        raise ValueError(f"project wiki path escapes root: {relative}")
    return target


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate manifest key: {key}")
        result[key] = value
    return result


def load_manifest(project_root: Path) -> dict[str, Any]:
    root = project_root.resolve()
    path = contained_file(root, "wiki/manifest.json")
    manifest = json.loads(
        path.read_text(encoding="utf-8"), object_pairs_hook=_unique_pairs
    )
    if not isinstance(manifest, dict) or manifest.get("version") != 1:
        raise ValueError("unsupported project wiki manifest version")
    if not isinstance(manifest.get("project"), str) or not manifest["project"].strip():
        raise ValueError("project wiki manifest requires a project name")
    if not isinstance(manifest.get("pages"), dict):
        raise ValueError("project wiki manifest requires an ID-to-page map")
    return manifest


def resolve_wiki_root(project_root: str | None, default_root: Path) -> Path:
    if project_root is None:
        return Path(default_root)
    if not project_root or not Path(project_root).is_absolute():
        raise ValueError("project_root must be an explicit absolute path")
    root = Path(project_root).resolve()
    load_manifest(root)
    return root / "wiki"


def save_manifest(project_root: Path, manifest: dict[str, Any]) -> None:
    path = contained_file(project_root.resolve(), "wiki/manifest.json")
    temporary = path.with_suffix(".json.tmp")
    if temporary.is_symlink():
        raise ValueError("project wiki manifest temporary path is a symlink")
    temporary.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def register_project_page(
    project_root: Path, rel_path: str, mirror_name: str | None = None
) -> str:
    manifest = load_manifest(project_root)
    source = contained_file(project_root / "wiki", rel_path)
    number = parse_decision_filename(source.name)
    if not source.is_file() or number is None:
        raise ValueError("a canonical ADR page must exist before registration")
    identifier = decision_id(number)
    if not rel_path.startswith("adr/"):
        raise ValueError("only ADR pages can be registered for mirroring")
    entry = {"path": rel_path, "mirror": mirror_name or "ADR-" + source.name}
    name = entry["mirror"]
    if Path(name).name != name or not name.endswith(".md"):
        raise ValueError("mirror must be a Markdown filename")
    if any(
        v.get("mirror") == name for k, v in manifest["pages"].items() if k != identifier
    ):
        raise ValueError(f"mirror filename already registered: {name}")
    previous = manifest["pages"].get(identifier)
    if previous is not None and previous != entry:
        raise ValueError(f"decision ID already registered: {identifier}")
    manifest["pages"][identifier] = entry
    save_manifest(project_root, manifest)
    return identifier
