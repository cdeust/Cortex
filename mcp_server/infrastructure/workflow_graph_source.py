"""Workflow graph source loader — reads every data stream the builder
consumes and returns plain dicts ready for ``core.workflow_graph_builder``.

Infrastructure layer only. No core imports. The heavy per-stream logic
lives in two sibling modules so this file stays under the project's
300-line ceiling:

* ``workflow_graph_source_pg``    — PostgreSQL-backed loaders
  (tool events, commands, command↔file, memories).
* ``workflow_graph_source_jsonl`` — session-JSONL-backed loaders
  (agents, discussion↔tool/agent/command/file, skill usage, MCP usage,
  the discussion list itself).

Tag vocabulary (``post_tool_capture.py`` line 165):
    ``["auto-captured", f"tool:{tool_name.lower()}"]``

Body markers (``post_tool_capture.py`` lines 152, 154, 156):
    Edit/Write:  ``**File:** `<abs_path>` ``
    Bash:        ``**Command:** `<cmd-truncated-200>` ``
    Read:        ``**Read:** `<abs_path>` ``
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable

from mcp_server.infrastructure.config import CLAUDE_DIR
from mcp_server.infrastructure.file_io import read_text_file
from mcp_server.infrastructure import workflow_graph_source_jsonl as _jsonl
from mcp_server.infrastructure import workflow_graph_source_pg as _pg
from mcp_server.shared.project_ids import (
    cwd_to_project_id,
    domain_id_from_label,
    project_id_to_label,
)

_TOOL_TAG_RE = re.compile(r"^tool:([a-z]+)$")
_TOOL_NAMES = frozenset(
    {"edit", "write", "bash", "read", "grep", "glob", "task"}
)


def _cmd_hash(cmd: str) -> str:
    return hashlib.sha1(cmd.encode("utf-8")).hexdigest()[:12]


def _first_line(text: str) -> str:
    for ln in text.splitlines():
        s = ln.strip()
        if s:
            return s
    return text.strip()


def _domain_from_directory(directory: str | None) -> str | None:
    if not directory:
        return None
    label = project_id_to_label(cwd_to_project_id(directory))
    return domain_id_from_label(label) or None


def _domain_from_project_dir(project_dir: str) -> str:
    """Claude's mangled project dir name → kebab-case domain id."""
    if not project_dir:
        return ""
    return domain_id_from_label(project_id_to_label(project_dir))


def _tool_from_tags(tags: Iterable[str]) -> str | None:
    for t in tags or []:
        m = _TOOL_TAG_RE.match(str(t))
        if m and m.group(1) in _TOOL_NAMES:
            return m.group(1).capitalize()
    return None


def _iter_skill_files() -> Iterable[Path]:
    user_root = CLAUDE_DIR / "skills"
    if user_root.exists():
        yield from (p for p in user_root.rglob("*.md") if p.is_file())
    plugins_root = CLAUDE_DIR / "plugins" / "cache"
    if plugins_root.exists():
        for p in plugins_root.rglob("skills/*.md"):
            if p.is_file():
                yield p


def _iter_hook_sources() -> Iterable[tuple[Path, str | None]]:
    """Yield ``(settings-path, domain-id)`` pairs. ``None`` → global."""
    user_settings = CLAUDE_DIR / "settings.json"
    if user_settings.is_file():
        yield user_settings, None
    plugins_root = CLAUDE_DIR / "plugins" / "cache"
    if not plugins_root.exists():
        return
    for hooks_json in plugins_root.rglob("hooks/hooks.json"):
        if hooks_json.is_file():
            yield hooks_json, None
    for plugin_settings in plugins_root.rglob(".claude/settings.json"):
        if plugin_settings.is_file():
            yield plugin_settings, None


class WorkflowGraphSource:
    """Facade over the per-stream loaders. Every method returns plain
    dicts that the core ``WorkflowGraphBuilder`` ingests verbatim."""

    # ── 1. Tool events (PG memories + JSONL tool_uses union) ──────────
    def load_tool_events(self, pg_store) -> list[dict[str, Any]]:
        """Every file touch Claude ever performed, across both the
        post_tool_capture memory stream (covers Edit/Write/Read) AND
        session JSONL tool_uses (covers Grep/Glob/NotebookRead/Bash
        paths and subagent transcripts Explore/Plan used). Duplicate
        ``(tool, file, domain)`` rows are merged by the builder's
        ``_dedupe_and_link`` pass — counts sum, timestamp bounds widen."""
        pg_rows = _pg.load_tool_events(
            pg_store, _tool_from_tags, _domain_from_directory,
            _cmd_hash, _first_line,
        )
        jsonl_rows = _jsonl.load_file_access_events(_domain_from_project_dir)
        return pg_rows + jsonl_rows

    # ── 2. Skills (filesystem scan) ───────────────────────────────────
    def load_skills(self) -> list[dict[str, Any]]:
        skills: dict[str, dict[str, Any]] = {}
        for path in _iter_skill_files():
            name = path.stem
            if name in skills:
                continue
            skills[name] = {"name": name, "path": str(path), "domains": []}
        return list(skills.values())

    # ── 3. Hooks (settings.json files) ────────────────────────────────
    def load_hooks(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for path, domain in _iter_hook_sources():
            try:
                data = json.loads(read_text_file(path) or "{}")
            except (OSError, ValueError):
                continue
            hooks_block = data.get("hooks")
            if not isinstance(hooks_block, dict):
                continue
            for event, entries in hooks_block.items():
                for entry in entries or []:
                    matcher = entry.get("matcher") or ""
                    for h in entry.get("hooks") or []:
                        cmd = h.get("command")
                        if not cmd:
                            continue
                        out.append({
                            "event": event, "matcher": matcher,
                            "command": cmd, "domain": domain,
                        })
        return out

    # ── 4. Agents (JSONL) ─────────────────────────────────────────────
    def load_agent_events(self) -> list[dict[str, Any]]:
        return _jsonl.load_agent_events(_domain_from_project_dir)

    # ── 5. Commands (PG) ──────────────────────────────────────────────
    def load_command_events(self, pg_store) -> list[dict[str, Any]]:
        return _pg.load_command_events(
            pg_store, _domain_from_directory, _cmd_hash, _first_line,
        )

    # ── 6. Memories (PG) ──────────────────────────────────────────────
    def load_memories(self, pg_store, min_heat: float = 0.0,
                      limit: int = 10000) -> list[dict[str, Any]]:
        return _pg.load_memories(pg_store, min_heat=min_heat, limit=limit)

    # ── 7. Discussions (JSONL metadata) ───────────────────────────────
    def load_discussions(self, session_store=None) -> list[dict[str, Any]]:
        _ = session_store
        return _jsonl.load_discussions(_domain_from_project_dir)

    # ── 8. Discussion ↔ tool / agent / command / file (JSONL) ─────────
    def load_discussion_tool_uses(self) -> list[dict[str, Any]]:
        return _jsonl.load_discussion_tool_uses(_domain_from_project_dir)

    def load_discussion_agents(self) -> list[dict[str, Any]]:
        return _jsonl.load_discussion_agents(_domain_from_project_dir)

    def load_discussion_commands(self) -> list[dict[str, Any]]:
        return _jsonl.load_discussion_commands(
            _domain_from_project_dir, _cmd_hash, _first_line,
        )

    def load_discussion_files(self) -> list[dict[str, Any]]:
        return _jsonl.load_discussion_files(_domain_from_project_dir)

    # ── 9. Command → file (PG) ────────────────────────────────────────
    def load_command_files(self, pg_store,
                           known_paths: Iterable[str]) -> list[dict[str, Any]]:
        return _pg.load_command_files(
            pg_store, known_paths, _cmd_hash, _first_line,
        )

    # ── 10. Skill usage + 11. MCP usage (JSONL) ───────────────────────
    def load_skill_usage(self) -> list[dict[str, Any]]:
        return _jsonl.load_skill_usage(_domain_from_project_dir)

    def load_mcp_usage(self) -> list[dict[str, Any]]:
        return _jsonl.load_mcp_usage(_domain_from_project_dir)


__all__ = ["WorkflowGraphSource"]
