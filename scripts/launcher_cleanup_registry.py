"""Conservative protection set for the launcher's dependency cleanup.

Identity mapping and settings scopes are documented at
https://code.claude.com/docs/en/plugins-reference . The registry's plugins ->
list[installPath] shape is exercised by tests_py/infrastructure/
test_pipeline_discovery.py. This cleanup additionally requires explicit scope
and projectPath for project/local records; incomplete/unknown schemas refuse
cleanup instead of interpreting missing information as uninstallation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from launcher_cleanup_fs import CleanupRefusedError, read_object


def identity(plugin_id: str) -> str:
    """Apply Claude's documented identifier-to-data-directory mapping."""
    name, separator, marketplace = plugin_id.partition("@")
    if (
        not name
        or not separator
        or not marketplace
        or "@" in marketplace
        or any(char.isspace() for char in plugin_id)
    ):
        raise CleanupRefusedError(f"unsupported plugin identifier: {plugin_id!r}")
    return re.sub(r"[^a-zA-Z0-9_-]", "-", plugin_id)


def _absolute_path(value: object, field: str) -> Path:
    if not isinstance(value, str) or not value:
        raise CleanupRefusedError(f"missing or invalid {field}")
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts:
        raise CleanupRefusedError(f"{field} must be absolute without '..'")
    return path


def _project(entry: object) -> Path | None:
    """Unknown scope must not conceal project-specific protection settings."""
    if not isinstance(entry, dict):
        raise CleanupRefusedError("installed plugin entry is not an object")
    _absolute_path(entry.get("installPath"), "installPath")
    scope = entry.get("scope")
    if not isinstance(scope, str) or scope not in {"user", "project", "local"}:
        raise CleanupRefusedError(
            "missing or unsupported install scope (including managed)"
        )
    if scope in {"project", "local"} or "projectPath" in entry:
        return _absolute_path(entry.get("projectPath"), "projectPath")
    return None


def _installed(path: Path) -> tuple[set[str], set[Path]]:
    records = read_object(path).get("plugins")
    if not isinstance(records, dict):
        raise CleanupRefusedError(f"missing or invalid plugins registry: {path}")
    protected: set[str] = set()
    projects: set[Path] = set()
    for plugin_id, entries in records.items():
        protected.add(identity(plugin_id))
        if not isinstance(entries, list) or not entries:
            raise CleanupRefusedError(f"missing install records: {plugin_id}")
        for entry in entries:
            project = _project(entry)
            if project is not None:
                projects.add(project)
    return protected, projects


def _settings(path: Path) -> set[str]:
    records = read_object(path).get("enabledPlugins")
    if not isinstance(records, dict):
        raise CleanupRefusedError(f"missing or invalid enabledPlugins: {path}")
    if not all(isinstance(value, bool) for value in records.values()):
        raise CleanupRefusedError(f"non-boolean enabledPlugins entry: {path}")
    # False means disabled, not uninstalled; protect every key.
    return {identity(plugin_id) for plugin_id in records}


@dataclass(frozen=True)
class CleanupScope:
    """Explicit root and current identity; never defaults to the home folder."""

    claude_root: Path
    current_deps: Path

    @property
    def data_root(self) -> Path:
        return self.claude_root / "plugins" / "data"

    def current_identity(self) -> str:
        if (
            not self.claude_root.is_absolute()
            or ".." in self.claude_root.parts
            or self.current_deps.name != "deps"
            or self.current_deps.parent.parent != self.data_root
        ):
            raise CleanupRefusedError(
                "current CLAUDE_PLUGIN_DATA must be directly under root/plugins/data"
            )
        return self.current_deps.parent.name


def protections(scope: CleanupScope) -> set[str]:
    """Fail closed unless every discovered protection source is readable."""
    current = scope.current_identity()
    protected, projects = _installed(
        scope.claude_root / "plugins" / "installed_plugins.json"
    )
    protected.update(_settings(scope.claude_root / "settings.json"))
    for project in sorted(projects):
        protected.update(_settings(project / ".claude" / "settings.json"))
        protected.update(_settings(project / ".claude" / "settings.local.json"))
    protected.add(current)
    return protected
