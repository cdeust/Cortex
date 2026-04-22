"""Session-JSONL-backed loaders for the workflow graph.

Scans every conversation transcript in ``~/.claude/projects/*/*.jsonl`` for
tool-use blocks, slash commands, MCP invocations, and discussion metadata.
Pure infrastructure — no core imports. Split from ``workflow_graph_source``
to keep that module under the 300-line project ceiling.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable

from mcp_server.infrastructure.config import CLAUDE_DIR
from mcp_server.infrastructure.scanner import (
    discover_conversations,
    iter_tool_uses,
    read_head_tail,
)
from mcp_server.infrastructure.file_io import list_dir

_SLASH_RE = re.compile(r"^\s*/([A-Za-z][A-Za-z0-9:_\-]*)")
_MCP_NAME_RE = re.compile(r"^mcp__([A-Za-z0-9_]+)__([A-Za-z0-9_]+)$")

# Claude surfaces several tool names that collapse to a single hub.
# The value ``""`` means "not a graph hub"; callers skip those.
_TOOL_NORMALIZE: dict[str, str] = {
    "Edit": "Edit", "MultiEdit": "Edit", "NotebookEdit": "Edit",
    "Write": "Write",
    "Read": "Read", "NotebookRead": "Read",
    "Grep": "Grep",
    "Glob": "Glob",
    "Bash": "Bash",
    "Task": "Task", "Agent": "Task",
}
_AGENT_TOOL_NAMES = frozenset({"Task", "Agent"})
# Every Claude tool whose ``input`` carries a file path we can surface.
# The read/search tools (Grep/Glob/NotebookRead) open files just as much
# as Edit/Write — the user asked for full visibility on everything
# Claude touched, not just authorship.
_FILE_INPUT_TOOLS = frozenset({
    "Edit", "Write", "Read", "MultiEdit", "NotebookEdit", "NotebookRead",
    "Glob", "Grep",
})
# Path-like tokens inside Bash commands (cat / tail / less / head / vim …)
# that implicitly open a file. Matches /abs or ~/rel or ./rel paths with
# at least one separator, at least 3 chars past the prefix.
_BASH_PATH_RE = re.compile(r"(?:^|[\s=])((?:\.{1,2}/|~/|/)[^\s`'\"]{3,})")
_SKIP_SKILL_PREFIXES = frozenset({"help", "clear", "reset"})


def normalize_tool_name(name: str) -> str:
    return _TOOL_NORMALIZE.get(name, "")


def iter_session_paths(domain_from_project_dir) -> Iterable[
    tuple[str, str, Path]
]:
    """Yield ``(session_id, domain_id, jsonl_path)`` for every session
    transcript under ``CLAUDE_DIR/projects/<project>/*.jsonl``.

    Subagent transcripts (e.g. ``<sid>-subagent-<type>.jsonl`` from the
    Explore / Plan / research agents) are included — the user asked for
    full visibility on every file Claude accessed, not just the top-level
    conversation. The subagent session id collapses into the parent id
    so the discussion node still groups all its work together.
    """
    projects_dir = CLAUDE_DIR / "projects"
    for pdir in list_dir(projects_dir, with_file_types=True) or []:
        if not pdir.is_dir():
            continue
        domain = domain_from_project_dir(pdir.name)
        for entry in list_dir(
            projects_dir / pdir.name, with_file_types=True
        ) or []:
            if not entry.is_file() or not entry.name.endswith(".jsonl"):
                continue
            stem = entry.name.rsplit(".", 1)[0]
            # Collapse subagent sessions into their parent so all
            # Explore/Plan file access rolls up into the parent
            # discussion node.
            sid = stem.split("-subagent-")[0].split("-explore-")[0]
            yield sid, domain, projects_dir / pdir.name / entry.name


def load_agent_events(domain_from_project_dir) -> list[dict[str, Any]]:
    """Scan every JSONL in full for Task tool_use blocks. No pg_store —
    subagent spawns live exclusively in session transcripts."""
    buckets: dict[tuple[str, str], int] = {}
    for _sid, domain, path in iter_session_paths(domain_from_project_dir):
        for tu in iter_tool_uses(path):
            if tu.get("name") not in _AGENT_TOOL_NAMES:
                continue
            sub = (tu.get("input") or {}).get("subagent_type")
            if not sub:
                continue
            key = (str(sub), domain)
            buckets[key] = buckets.get(key, 0) + 1
    return [
        {"subagent_type": s, "domain": d, "count": n}
        for (s, d), n in buckets.items()
    ]


def load_discussion_tool_uses(
    domain_from_project_dir,
) -> list[dict[str, Any]]:
    """For each session, which tool kinds it used and how often."""
    buckets: dict[tuple[str, str, str], int] = {}
    for sid, domain, path in iter_session_paths(domain_from_project_dir):
        for tu in iter_tool_uses(path):
            tool = normalize_tool_name(tu.get("name") or "")
            if not tool:
                continue
            key = (sid, domain, tool)
            buckets[key] = buckets.get(key, 0) + 1
    return [
        {"session_id": s, "domain": d, "tool": t, "count": n}
        for (s, d, t), n in buckets.items()
    ]


def load_discussion_agents(
    domain_from_project_dir,
) -> list[dict[str, Any]]:
    """Per-session Task spawn events."""
    buckets: dict[tuple[str, str, str], int] = {}
    for sid, domain, path in iter_session_paths(domain_from_project_dir):
        for tu in iter_tool_uses(path):
            if tu.get("name") not in _AGENT_TOOL_NAMES:
                continue
            sub = (tu.get("input") or {}).get("subagent_type")
            if not sub:
                continue
            key = (sid, domain, str(sub))
            buckets[key] = buckets.get(key, 0) + 1
    return [
        {"session_id": s, "domain": d, "subagent_type": a, "count": n}
        for (s, d, a), n in buckets.items()
    ]


def load_discussion_commands(
    domain_from_project_dir, cmd_hash, first_line,
) -> list[dict[str, Any]]:
    """Per-session Bash commands: session → (cmd, cmd_hash, count)."""
    buckets: dict[tuple[str, str, str], int] = {}
    for sid, _domain, path in iter_session_paths(domain_from_project_dir):
        for tu in iter_tool_uses(path):
            if tu.get("name") != "Bash":
                continue
            cmd = (tu.get("input") or {}).get("command") or ""
            cmd = first_line(str(cmd))
            if not cmd:
                continue
            h = cmd_hash(cmd)
            key = (sid, h, cmd)
            buckets[key] = buckets.get(key, 0) + 1
    return [
        {"session_id": s, "cmd_hash": h, "cmd": c, "count": n}
        for (s, h, c), n in buckets.items()
    ]


def load_discussion_files(
    domain_from_project_dir,
) -> list[dict[str, Any]]:
    """For each session, return ``(session_id, file_path, count)``.

    Covers every way Claude opens a file:
      * Read / Write / Edit / MultiEdit / NotebookEdit / NotebookRead
        (``file_path`` / ``path`` / ``notebook_path``)
      * Glob (``pattern`` is included when it matches a known file,
        routed through load_command_files at builder time)
      * Grep (``path`` for the search root)
      * Bash commands that reference absolute / relative paths
        (``cat``, ``head``, ``tail``, ``vim``, ``less``, pipelines …)
    Sessions include subagent transcripts from Explore / Plan / research
    agents; ``iter_session_paths`` folds their ids into the parent.
    """
    buckets: dict[tuple[str, str], int] = {}
    for sid, _domain, path in iter_session_paths(domain_from_project_dir):
        for tu in iter_tool_uses(path):
            _collect_tool_file_touches(tu, sid, buckets)
    return [
        {"session_id": s, "file_path": f, "count": n}
        for (s, f), n in buckets.items()
    ]


def _collect_tool_file_touches(tu: dict, sid: str,
                               buckets: dict) -> None:
    """Emit ``(sid, file_path)`` tuples for every file reference in ``tu``."""
    name = tu.get("name") or ""
    inp = tu.get("input") or {}
    if name in _FILE_INPUT_TOOLS:
        for key in ("file_path", "path", "notebook_path"):
            fp = inp.get(key)
            if fp:
                _bump_file(buckets, sid, str(fp))
    if name == "Bash":
        cmd = str(inp.get("command") or "")
        for m in _BASH_PATH_RE.finditer(" " + cmd):
            tok = m.group(1).rstrip(".,;:)'\"")
            if tok.startswith(("/", "~/", "./", "../")):
                _bump_file(buckets, sid, tok)


def _bump_file(buckets: dict, sid: str, path: str) -> None:
    key = (sid, path)
    buckets[key] = buckets.get(key, 0) + 1


def load_skill_usage(domain_from_project_dir) -> list[dict[str, Any]]:
    """Record the user's slash commands per domain."""
    buckets: dict[tuple[str, str], int] = {}
    for _sid, domain, path in iter_session_paths(domain_from_project_dir):
        for rec in read_head_tail(path) or []:
            text = _extract_user_text(rec)
            if not text:
                continue
            m = _SLASH_RE.match(text)
            if not m:
                continue
            skill = m.group(1).split(":")[-1]
            if skill in _SKIP_SKILL_PREFIXES:
                continue
            key = (skill, domain)
            buckets[key] = buckets.get(key, 0) + 1
    return [
        {"name": s, "domain": d, "count": n}
        for (s, d), n in buckets.items()
    ]


def _extract_user_text(rec: dict) -> str:
    """Return the first text block of a user record, or ``""``."""
    if rec.get("type") != "user":
        return ""
    content = (rec.get("message") or {}).get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        for b in content:
            if isinstance(b, dict) and b.get("type") == "text":
                return b.get("text") or ""
    return ""


def load_mcp_usage(domain_from_project_dir) -> list[dict[str, Any]]:
    """Return ``(server, tool, domain, count)`` from assistant tool_uses."""
    buckets: dict[tuple[str, str, str], int] = {}
    for _sid, domain, path in iter_session_paths(domain_from_project_dir):
        for rec in read_head_tail(path) or []:
            if rec.get("type") != "assistant":
                continue
            content = (rec.get("message") or {}).get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") != "tool_use":
                    continue
                m = _MCP_NAME_RE.match(block.get("name") or "")
                if not m:
                    continue
                server, tool = m.group(1), m.group(2)
                key = (server, tool, domain)
                buckets[key] = buckets.get(key, 0) + 1
    return [
        {"server": s, "tool": t, "domain": d, "count": n}
        for (s, t, d), n in buckets.items()
    ]


def load_file_access_events(
    domain_from_project_dir,
) -> list[dict[str, Any]]:
    """Synthesize tool_events from session JSONL — one row per
    ``(tool, file_path, domain)`` with a count so the builder creates a
    file node for every path Claude touched (read, searched, opened via
    Bash, edited). Complements post_tool_capture memories which only
    cover Edit/Write/Read.

    Returns the same shape as ``load_tool_events`` in the PG loader:
    ``{tool, file_path, domain, count, first_ts, last_ts}``. The
    timestamp here is the JSONL record's ``timestamp`` when available,
    or ``None``.
    """
    buckets: dict[tuple[str, str | None, str], list] = {}
    for _sid, domain, path in iter_session_paths(domain_from_project_dir):
        for tu in iter_tool_uses(path):
            tool = normalize_tool_name(tu.get("name") or "")
            if not tool:
                continue
            for fp, ts in _tool_file_refs(tu):
                key = (tool, fp, domain)
                slot = buckets.get(key)
                if slot is None:
                    buckets[key] = [1, ts, ts]
                else:
                    slot[0] += 1
                    if ts and (slot[1] is None or ts < slot[1]):
                        slot[1] = ts
                    if ts and (slot[2] is None or ts > slot[2]):
                        slot[2] = ts
    return [
        {"tool": t, "file_path": fp, "domain": d,
         "count": n, "first_ts": first, "last_ts": last}
        for (t, fp, d), (n, first, last) in buckets.items()
    ]


def _tool_file_refs(tu: dict):
    """Yield ``(path, timestamp)`` pairs for every file this tool_use touched."""
    name = tu.get("name") or ""
    inp = tu.get("input") or {}
    ts = tu.get("timestamp") or tu.get("ts")
    if name in _FILE_INPUT_TOOLS:
        for key in ("file_path", "path", "notebook_path"):
            fp = inp.get(key)
            if fp:
                yield str(fp), ts
    if name == "Bash":
        cmd = str(inp.get("command") or "")
        seen: set[str] = set()
        for m in _BASH_PATH_RE.finditer(" " + cmd):
            tok = m.group(1).rstrip(".,;:)'\"")
            if tok not in seen and tok.startswith(("/", "~/", "./", "../")):
                seen.add(tok)
                yield tok, ts


def load_discussions(domain_from_project_dir) -> list[dict[str, Any]]:
    """Group session JSONL by domain via ``discover_conversations``.

    Every discussion carries its own timeline so the detail panel can
    render when the session started, how long it lasted, and the last
    activity timestamp.
    """
    return [
        {
            "session_id": conv.get("sessionId") or conv.get("project") or "",
            "domain": domain_from_project_dir(conv.get("project") or ""),
            "title": (conv.get("firstMessage") or "")[:60] or None,
            "message_count": int(conv.get("messageCount") or 0),
            "started_at": conv.get("startedAt"),
            "last_activity": conv.get("lastActivity") or conv.get("endedAt"),
            "duration_ms": conv.get("duration"),
        }
        for conv in discover_conversations()
    ]
