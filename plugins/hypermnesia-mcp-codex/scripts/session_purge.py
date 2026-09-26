"""Existing Claude session cleanup, with transcript deletion opt-in.

source: ADR-1092 (ported from the native-tested shared disk-hygiene hook).
Runtime scratch is removed after confirmed pushes and session end. Transcripts,
nested subagent transcripts and file history remain unless deletion is enabled.
With deletion enabled, the parallel Cortex lifecycle reader must finish before
removal. Protected files are retried at later lifecycle events. The host may
recreate its tasks directory until its process exits.
"""

import os

import transcript_policy
from pathlib import Path
import re
import shutil
import subprocess
import time

# source: native host UUID session identifiers; ADR-1092.
SESSION_ID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}")
# source: ps -o ppid=,comm= emits the parent PID and command fields.
PARENT_COMMAND_FIELDS = 2
TRANSCRIPT_READER = "hooks.session_lifecycle"
# source: original Claude hook bounds, measured in the native 2026-09-26 trial;
# operational waits, not eligibility thresholds. Codex does not use this wait.
READER_START_SECONDS = 1.0
# source: ADR-1092 (existing Claude reader wait bound).
READER_MAX_SECONDS = 15.0
# source: ADR-1092 (existing Claude reader polling interval).
POLL_SECONDS = 0.1
HOST_PATTERNS = (
    "file-history/{sid}",
    "session-env/{sid}",
    "security/*_{sid}.json",
    "security/*_{sid}.lock",
    "statusline/state/sessions/{sid}.*",
    "todos/{sid}-*.json",
    "debug/{sid}*",
    "projects/*/{sid}",
)
TRANSCRIPT_PATTERN = "projects/*/{sid}.jsonl"
# context-guard's compaction checkpoint: needed while the session runs, dead after.
ENDED_PATTERNS = ("memories/checkpoints/{sid}.md",)


def temp_root():
    base = Path(os.environ.get("CLAUDE_CODE_TMPDIR", "/tmp")).resolve()
    return base / f"claude-{os.getuid()}"


def claude_home():
    return Path(os.environ.get("CORTEX_CLAUDE_DIR") or "~/.claude").expanduser()


def checked(session):
    if not isinstance(session, str) or not SESSION_ID.fullmatch(session):
        raise ValueError("session id is not a UUID; no path built from it")
    return session


def scratch_entries(root, session):
    sid = checked(session)
    return [
        entry
        for pad in Path(root).glob(f"*/{sid}/scratchpad")
        if pad.is_dir() and not pad.is_symlink()
        for entry in pad.iterdir()
    ]


def home_paths(home, session, patterns):
    sid = checked(session)
    return [p for pat in patterns for p in Path(home).glob(pat.format(sid=sid))]


def remove(path, guard, dry_run):
    """guard(path) raises RuntimeError while a process holds the path open."""
    path = Path(path)
    if path.parent.resolve() != path.parent.absolute():
        return {"path": str(path), "protected": "symlink parent"}
    if not hasattr(os, "getuid"):
        return {"path": str(path), "protected": "host file ownership check unavailable"}
    if path.is_symlink():
        if not dry_run:
            path.unlink()  # Removes the link only, never its target.
        return {
            "path": str(path),
            "status": "would remove" if dry_run else "removed symlink",
        }
    if path.lstat().st_uid != os.getuid():
        return {"path": str(path), "protected": "foreign owner"}
    if path.is_dir():
        for _, dirs, files in os.walk(path, followlinks=False):
            if ".git" in dirs or ".git" in files:
                return {"path": str(path), "protected": "contains a Git checkout"}
    try:
        guard(str(path))
    except RuntimeError as exc:
        return {"path": str(path), "protected": str(exc)}
    if dry_run:
        return {"path": str(path), "status": "would remove"}
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()
    return {"path": str(path), "status": "removed"}


def remove_tree(path, guard):
    """One open file keeps only itself and its parents, not its closed siblings."""
    result = remove(path, guard, False)
    busy = result.get("protected", "").startswith("active process")
    if busy and path.is_dir() and not path.is_symlink():
        return [r for child in path.iterdir() for r in remove_tree(child, guard)]
    return [result]


def purge_now(locations, session, guard, dry_run=False):
    """Push time: the host keeps running, so its scratchpad directory stays."""
    home, root = locations
    sid = checked(session)
    patterns = cleanup_patterns(include_transcripts=False)
    found = home_paths(home, sid, patterns)
    for session_dir in Path(root).glob(f"*/{sid}"):
        if session_dir.is_dir() and not session_dir.is_symlink():
            found += [c for c in session_dir.iterdir() if c.name != "scratchpad"]
    results = [remove(p, guard, dry_run) for p in found + scratch_entries(root, sid)]
    return results + purge_transcripts(
        home, sid, guard, {"wait": lambda: not reader_running(), "dry_run": dry_run}
    )


def reader_running():
    """True while a Cortex SessionEnd hook (transcript reader) is running."""
    try:
        result = subprocess.run(
            ["pgrep", "-f", TRANSCRIPT_READER],
            text=True,
            capture_output=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return True  # Unknown counts as running; the bound still applies.
    if result.returncode not in (0, 1) or result.stderr.strip():
        return True
    own = {str(os.getpid()), str(os.getppid())}
    return any(pid not in own for pid in result.stdout.split())


def wait_for_reader(running=reader_running, clock=time.monotonic, sleep=time.sleep):
    """Wait for a reader that started, or give it a short window to start."""
    start, seen = clock(), False
    while clock() - start < READER_MAX_SECONDS:
        if running():
            seen = True
        elif seen or clock() - start >= READER_START_SECONDS:
            return True
        sleep(POLL_SECONDS)
    return False


def purge_ended(locations, session, guard, wait=wait_for_reader):
    """SessionEnd: everything of the ended session, scratchpad included."""
    home, root = locations
    sid = checked(session)
    patterns = cleanup_patterns(include_transcripts=False)
    found = home_paths(home, sid, patterns + ENDED_PATTERNS)
    found += list(Path(root).glob(f"*/{sid}"))
    results = [r for p in found for r in remove_tree(p, guard)]
    return results + purge_transcripts(home, sid, guard, {"wait": wait})


def purge_transcripts(home, sid, guard, options):
    wait, dry_run = options["wait"], options.get("dry_run", False)
    transcripts = (
        home_paths(home, sid, (TRANSCRIPT_PATTERN, "projects/*/{sid}"))
        if transcript_policy.delete_enabled()
        else []
    )
    if transcripts and not wait():
        return [
            {"path": str(p), "protected": "transcript reader still running"}
            for p in transcripts
        ]
    return [remove(p, guard, dry_run) for p in transcripts]


def host_pid(pid=None):
    """The Claude process up this hook's parent chain; None when not found."""
    pid = pid or os.getppid()
    while pid > 1:
        try:
            out = subprocess.run(
                ["ps", "-o", "ppid=,comm=", "-p", str(pid)],
                text=True,
                capture_output=True,
                timeout=5,
            ).stdout.split(None, 1)
        except (OSError, subprocess.TimeoutExpired):
            return None
        if len(out) < PARENT_COMMAND_FIELDS or not out[0].isdigit():
            return None
        if Path(out[1].strip()).name == "claude":
            return pid
        pid = int(out[0])
    return None


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def owns_tasks(root, session):
    """The host keeps its Bash outputs under the id active at its first Bash call,
    for its whole life: that tasks/ directory reappears after every /clear."""
    return any(d.is_dir() for d in Path(root).glob(f"*/{checked(session)}/tasks"))


def end_session(pending, locations, session, options):
    """SessionEnd: purge now; note the id when something must be retried."""
    home, root = locations
    guard, host = options["guard"], options["host"]
    wait = options.get("wait", wait_for_reader)
    tasks = owns_tasks(root, session)
    results = purge_ended((home, root), session, guard, wait)
    if tasks or any("protected" in r for r in results):
        pending[session] = {
            "host": host,
            "tasks": tasks,
            "scope": pending_scope(home, root),
        }
    return results


def retry_ended(pending, locations, current, options):
    """Retry only matching roots, keeping transcripts while their reader runs.

    Keep task ownership until its known host exits; unknown host state stays pending.
    """
    home, root = locations
    guard = options["guard"]
    is_alive = options.get("is_alive", alive)
    cancel_current = options.get("cancel_current", True)
    results = []
    for sid, record in list(pending.items()):
        if record.get("scope") != pending_scope(home, root):
            results.append(
                {"session": sid, "protected": "unknown or different Claude roots"}
            )
            continue
        if sid == current:
            if cancel_current:
                del pending[sid]  # SessionStart: its files are live again.
            continue
        done = purge_ended((home, root), sid, guard, wait=lambda: not reader_running())
        results += done
        host = record.get("host")
        kept = record.get("tasks") and (host is None or is_alive(host))
        if not kept and not any("protected" in r for r in done):
            del pending[sid]
    return results


def cleanup_patterns(include_transcripts=True):
    """Keep the rollout, nested subagent transcripts and rewind history by default.

    source: ADR-1092 (existing Claude selectors, unchanged for opt-in).
    """
    if transcript_policy.delete_enabled():
        if include_transcripts:
            return HOST_PATTERNS + (TRANSCRIPT_PATTERN,)
        return tuple(p for p in HOST_PATTERNS if p != "projects/*/{sid}")
    return tuple(
        p for p in HOST_PATTERNS if p not in ("file-history/{sid}", "projects/*/{sid}")
    )


def pending_scope(home, root):
    return {"home": str(Path(home).resolve()), "root": str(Path(root).resolve())}
