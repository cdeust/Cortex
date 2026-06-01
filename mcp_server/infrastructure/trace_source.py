"""Ordered, timestamped session-trace reader (infrastructure I/O).

Backs the domain-split execution-trace graph. Unlike
``workflow_graph_source_jsonl`` (which collapses tool use to per-session
counts), this preserves the full ordered causal chain: every user prompt
and assistant tool call in time order, with timestamps.

Three levels:
  * ``list_domains()``          -> L0 domain hubs
  * ``list_sessions(domain)``   -> L1 sessions in a domain
  * ``iter_session_events(sid)``-> L2 ordered prompt/action events

Pure I/O over ``~/.claude/projects/<project>/*.jsonl``. Returns plain
dicts; the node/edge vocabulary lives in ``core.session_trace``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator

from mcp_server.infrastructure.config import CLAUDE_DIR
from mcp_server.infrastructure.file_io import list_dir
from mcp_server.shared.project_ids import (
    domain_id_from_label,
    project_id_to_label,
)


def project_dir_to_label(project_dir_name: str) -> str:
    """Human-readable label for a Claude project directory name."""
    return project_id_to_label(project_dir_name)


def project_dir_to_domain(project_dir_name: str) -> str:
    """Canonical ``domain:<kebab>`` id for a project directory name.

    Derived from the human label so it matches the L0 hub ids the
    frontend filters on (e.g. ``-Users-cdeust-Developments-Cortex`` ->
    label "Cortex" -> ``domain:cortex``).
    """
    label = project_id_to_label(project_dir_name)
    return f"domain:{domain_id_from_label(label) or 'unknown'}"

# Tools that are real graph actions (skip TodoWrite / internal noise).
_ACTION_TOOLS = frozenset(
    {
        "Read",
        "Edit",
        "MultiEdit",
        "Write",
        "NotebookEdit",
        "NotebookRead",
        "Grep",
        "Glob",
        "Bash",
        "Task",
        "Agent",
        "WebFetch",
        "WebSearch",
    }
)


def _projects_dir() -> Path:
    return CLAUDE_DIR / "projects"


def _iter_project_dirs():
    for pdir in list_dir(_projects_dir(), with_file_types=True) or []:
        if pdir.is_dir():
            yield pdir


def _session_files(project_dir: Path):
    """Yield .jsonl session files under a project dir (incl. subagents)."""
    for entry in list_dir(project_dir, with_file_types=True) or []:
        if entry.is_file() and entry.name.endswith(".jsonl"):
            yield project_dir / entry.name


def _first_user_text(rec_content: Any) -> str:
    if isinstance(rec_content, str):
        return rec_content
    if isinstance(rec_content, list):
        for b in rec_content:
            if isinstance(b, dict) and b.get("type") == "text":
                return b.get("text") or ""
    return ""


# ── L0: domains ─────────────────────────────────────────────────────────


def list_domains() -> list[dict[str, Any]]:
    """Return one collapsed domain hub per project dir that has sessions."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for pdir in _iter_project_dirs():
        files = list(_session_files(pdir))
        if not files:
            continue
        did = project_dir_to_domain(pdir.name)
        if did in seen:
            # Merge session count into the existing hub.
            for d in out:
                if d["id"] == did:
                    d["session_count"] += len(files)
            continue
        seen.add(did)
        out.append(
            {
                "id": did,
                "kind": "domain",
                "type": "domain",
                "label": project_dir_to_label(pdir.name),
                "domain_id": did,
                "session_count": len(files),
                # ``expandable`` (not ``collapsed``): the force-graph
                # renderer hides nodes flagged ``collapsed`` unless their
                # parent is in its expanded-set, which trace doesn't use
                # (it fetches children on click). ``collapsed`` here would
                # hide every domain hub.
                "expandable": True,
            }
        )
    return out


# ── L1: sessions in a domain ────────────────────────────────────────────


def _scan_session_meta(path: Path) -> dict[str, Any] | None:
    """Cheap first/last/first-prompt scan of one session file."""
    sid = None
    first_ts = None
    last_ts = None
    first_prompt = ""
    git_branch = None
    n_actions = 0
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for raw in f:
                s = raw.strip()
                if not s:
                    continue
                try:
                    rec = json.loads(s)
                except (json.JSONDecodeError, ValueError):
                    continue
                if sid is None and rec.get("sessionId"):
                    sid = rec["sessionId"]
                if git_branch is None and rec.get("gitBranch"):
                    git_branch = rec["gitBranch"]
                ts = rec.get("timestamp")
                if ts:
                    if first_ts is None or ts < first_ts:
                        first_ts = ts
                    if last_ts is None or ts > last_ts:
                        last_ts = ts
                rtype = rec.get("type")
                if rtype == "user" and not first_prompt:
                    content = (rec.get("message") or {}).get("content")
                    txt = _first_user_text(content)
                    # skip tool_result-only user records
                    if txt.strip():
                        first_prompt = txt
                elif rtype == "assistant":
                    content = (rec.get("message") or {}).get("content")
                    if isinstance(content, list):
                        for b in content:
                            if (
                                isinstance(b, dict)
                                and b.get("type") == "tool_use"
                                and (b.get("name") or "") in _ACTION_TOOLS
                            ):
                                n_actions += 1
    except OSError:
        return None
    if sid is None:
        sid = path.stem
    return {
        "session_id": sid,
        "first_ts": first_ts,
        "last_ts": last_ts,
        "first_prompt": first_prompt,
        "git_branch": git_branch,
        "action_count": n_actions,
        "path": str(path),
    }


def _short(text: str, n: int = 60) -> str:
    s = " ".join(str(text or "").split())
    return s[: n - 1] + "…" if len(s) > n else s


def list_sessions(domain_id: str) -> dict[str, Any]:
    """Return L1 session nodes + ``has_session`` edges for one domain.

    ``domain_id`` is the canonical ``domain:<label>`` id from L0.
    """
    nodes: list[dict] = []
    edges: list[dict] = []
    for pdir in _iter_project_dirs():
        if project_dir_to_domain(pdir.name) != domain_id:
            continue
        for path in _session_files(pdir):
            # skip subagent transcripts at L1 — they fold into the parent
            # chain at L2; listing them as top-level sessions is noise.
            if "-subagent-" in path.name or "-explore-" in path.name:
                continue
            meta = _scan_session_meta(path)
            if not meta or meta["action_count"] == 0:
                continue
            sid = meta["session_id"]
            nid = f"session:{sid}"
            label = _short(meta["first_prompt"] or sid, 50)
            nodes.append(
                {
                    "id": nid,
                    "kind": "session",
                    "type": "session",
                    "label": label,
                    "domain_id": domain_id,
                    "session_id": sid,
                    "started_at": meta["first_ts"],
                    "last_activity": meta["last_ts"],
                    "git_branch": meta["git_branch"],
                    "action_count": meta["action_count"],
                    "expandable": True,
                }
            )
            edges.append(
                {
                    "id": f"{domain_id}->{nid}",
                    "source": domain_id,
                    "target": nid,
                    "kind": "has_session",
                    "type": "has_session",
                }
            )
    # newest first
    nodes.sort(key=lambda n: n.get("started_at") or "", reverse=True)
    return {"nodes": nodes, "edges": edges}


# ── L2: ordered events for one session ──────────────────────────────────


def _find_session_files(session_id: str) -> list[Path]:
    """Locate every transcript (parent + subagents) for a session id."""
    matches: list[Path] = []
    for pdir in _iter_project_dirs():
        for path in _session_files(pdir):
            stem = path.stem
            base = stem.split("-subagent-")[0].split("-explore-")[0]
            if base == session_id or stem == session_id:
                matches.append(path)
    return matches


def iter_session_events(session_id: str) -> list[dict[str, Any]]:
    """Return the ordered prompt/action event list for one session.

    Each event is ``{"kind": "prompt"|"action", "ts", "line", ...}``.
    Prompts carry ``text``; actions carry ``tool`` + ``input``. Sorted by
    (timestamp, line) so the causal spine is in true execution order.
    Includes subagent transcripts folded into the same session.
    """
    events: list[dict[str, Any]] = []
    for path in _find_session_files(session_id):
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                for line_no, raw in enumerate(f, start=1):
                    s = raw.strip()
                    if not s:
                        continue
                    try:
                        rec = json.loads(s)
                    except (json.JSONDecodeError, ValueError):
                        continue
                    ts = rec.get("timestamp")
                    rtype = rec.get("type")
                    if rtype == "user":
                        content = (rec.get("message") or {}).get("content")
                        txt = _first_user_text(content)
                        if txt.strip():
                            events.append(
                                {
                                    "kind": "prompt",
                                    "text": txt,
                                    "ts": ts,
                                    "line": line_no,
                                }
                            )
                    elif rtype == "assistant":
                        content = (rec.get("message") or {}).get("content")
                        if not isinstance(content, list):
                            continue
                        for b in content:
                            if not isinstance(b, dict):
                                continue
                            if b.get("type") != "tool_use":
                                continue
                            name = b.get("name") or ""
                            if name not in _ACTION_TOOLS:
                                continue
                            events.append(
                                {
                                    "kind": "action",
                                    "tool": name,
                                    "input": b.get("input") or {},
                                    "ts": ts,
                                    "line": line_no,
                                }
                            )
        except OSError:
            continue
    events.sort(key=lambda e: (e.get("ts") or "", e.get("line") or 0))
    return events


__all__ = ["list_domains", "list_sessions", "iter_session_events"]
