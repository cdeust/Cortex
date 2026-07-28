"""Compose + write a task-record ADR draft at session end.

Pulled out of ``record_session_end`` so the handler stays under the size
limit and so the writer is unit-testable on its own.

The flow:

  1. Gather session evidence — commits in this session window, memories
     tagged with decision/lesson/fix/feature, files changed.
  2. Skip silently if the session wasn't substantive
     (``is_substantive`` returns False).
  3. Pick the next ADR number for the domain — scans
     ``<wiki>/adr/<domain>/`` for the highest existing ``NNNN-*.md``.
  4. Build the draft via ``build_task_record`` and write the page via
     the existing wiki write path.

Failure is non-fatal — record_session_end must continue regardless.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

from mcp_server.core.auto_task_record import (
    TaskRecordInputs,
    build_task_record,
    is_substantive,
)
from mcp_server.infrastructure.config import WIKI_ROOT
from mcp_server.shared.subprocess_safe import run_with_hard_timeout
from mcp_server.observability import silent_failure

logger = logging.getLogger(__name__)


_ADR_FILENAME_RE = re.compile(r"^(\d{4})-")


def _next_adr_number(wiki_root: Path, domain: str) -> int:
    """Pick the next free ADR number for ``domain``.

    Scans ``<wiki>/adr/<domain>/`` for filenames matching
    ``NNNN-<slug>.md`` and returns max+1. Returns 1 when the directory
    is empty or missing.
    """
    dom_dir = wiki_root / "adr" / domain
    if not dom_dir.is_dir():
        return 1
    highest = 0
    for entry in dom_dir.iterdir():
        if not entry.name.endswith(".md"):
            continue
        m = _ADR_FILENAME_RE.match(entry.name)
        if m:
            try:
                n = int(m.group(1))
                if n > highest:
                    highest = n
            except ValueError:
                continue
    return highest + 1


def _git_commits_in_window(cwd: str, since_minutes: float) -> list[dict]:
    """Return commits authored under ``cwd`` in the trailing window.

    Each entry: ``{"hash", "message", "files", "timestamp"}``. Returns
    an empty list when ``cwd`` isn't a git repo, git fails, or the call
    times out.

    Reached from the live ``record_session_end`` tool
    (``record_session_end.py``). Execution goes through
    ``run_with_hard_timeout`` (not ``subprocess.check_output``) so a
    timeout kills the child without CPython's own post-kill
    ``communicate()`` retry — the Windows pipe-handle deadlock described
    in cdeust/Cortex#91/#94. ``None`` (timeout/spawn-failure/non-zero
    exit) degrades to the same empty-list result as a git failure always
    produced here — no caller-visible behavior change.
    """
    if not cwd or not os.path.isdir(cwd):
        return []
    since = f"{int(max(since_minutes, 1))} minutes ago"
    out = run_with_hard_timeout(
        [
            "git",
            "-C",
            cwd,
            "log",
            f"--since={since}",
            "--pretty=format:%H%n%s%n%ai%n--BODY--",
            "--name-only",
        ],
        timeout=10,
        encoding="utf-8",
    )
    if out is None:
        return []
    commits: list[dict] = []
    current: dict[str, Any] | None = None
    files: list[str] = []
    lines_iter = iter(out.splitlines())
    try:
        while True:
            sha = next(lines_iter)
            if not sha:
                continue
            subj = next(lines_iter, "")
            ts = next(lines_iter, "")
            # Skip the BODY marker line.
            marker = next(lines_iter, "")
            if marker != "--BODY--":
                # No marker — recover by treating it as the first file.
                files = [marker] if marker else []
            else:
                files = []
            # Then file paths until we hit a blank line or a new sha.
            while True:
                ln = next(lines_iter, None)
                if ln is None:
                    break
                if ln == "":
                    break
                files.append(ln)
            commits.append(
                {
                    "hash": sha,
                    "message": subj,
                    "timestamp": ts,
                    "files": files,
                }
            )
    except StopIteration:
        if current is not None:
            commits.append(current)
    return commits


def _session_memories(store, session_id: str, domain: str) -> list[dict]:
    """Pull memories captured during this session.

    Uses a simple recent-memories fetch and filters by session_id tag.
    Returns at most 50 entries to keep the draft tractable.
    """
    try:
        # heads_only: task-record drafts fold memory content in —
        # supersession chain heads only.
        recent = store.get_recently_accessed_memories(limit=200, heads_only=True)
    except Exception as exc:  # noqa: BLE001 — mechanism boundary; failure is observable via silent_failure
        silent_failure.note("auto_task_record.recent_memories", exc)
        recent = []
    out: list[dict] = []
    target_tag = f"session:{session_id}"
    for m in recent:
        tags = m.get("tags") or []
        if any(t == target_tag for t in tags) or (
            m.get("domain") == domain and m.get("session_id") == session_id
        ):
            out.append(m)
        if len(out) >= 50:
            break
    return out


def maybe_write_task_record(
    *,
    session_id: str,
    domain: str,
    cwd: str | None,
    duration_seconds: float | None,
    turn_count: int | None,
    tools_used: list[str],
    store,
) -> dict[str, Any]:
    """Compose and write an ADR draft for this session.

    Returns a status dict:
      * ``status: "skipped"`` — session wasn't substantive.
      * ``status: "written", path: ..., adr_number: ...`` — draft saved.
      * ``status: "error", reason: ...`` — non-fatal failure (e.g.
        wiki root unwritable). Caller logs and proceeds.
    """
    if not domain:
        return {"status": "skipped", "reason": "no_domain"}

    # Look back over the session duration plus a small margin, so any
    # commit made during the session lands in the window even if the
    # duration arg is slightly under-counted.
    window_minutes = (duration_seconds / 60.0 + 5.0) if duration_seconds else 60.0
    commits = _git_commits_in_window(cwd or "", window_minutes)
    memories = _session_memories(store, session_id, domain) if store else []

    changed_files: list[str] = []
    seen: set[str] = set()
    for c in commits:
        for f in c.get("files") or []:
            if f and f not in seen:
                changed_files.append(f)
                seen.add(f)

    inputs = TaskRecordInputs(
        session_id=session_id,
        domain=domain,
        cwd=cwd or "",
        duration_seconds=duration_seconds,
        turn_count=turn_count,
        commits=commits,
        memories=memories,
        changed_files=changed_files,
        tools_used=list(tools_used or []),
    )

    if not is_substantive(inputs):
        return {
            "status": "skipped",
            "reason": "not_substantive",
            "commits": len(commits),
            "memories": len(memories),
            "tools": len(tools_used or []),
        }

    wiki_root = Path(WIKI_ROOT)
    try:
        adr_num = _next_adr_number(wiki_root, domain)
        record = build_task_record(inputs, adr_number=adr_num)
        page_path = wiki_root / record.suggested_path
        page_path.parent.mkdir(parents=True, exist_ok=True)
        page_path.write_text(record.body, encoding="utf-8")
        return {
            "status": "written",
            "path": record.suggested_path,
            "adr_number": adr_num,
            "title": record.title,
            "evidence": {
                "commits": len(commits),
                "memories": len(memories),
                "changed_files": len(changed_files),
            },
        }
    except Exception as exc:  # noqa: BLE001 — last-resort boundary — failure is logged; degraded mode continues
        logger.warning("auto-task-record write failed (non-fatal): %s", exc)
        return {"status": "error", "reason": f"{type(exc).__name__}: {exc}"}


__all__ = ["maybe_write_task_record"]
