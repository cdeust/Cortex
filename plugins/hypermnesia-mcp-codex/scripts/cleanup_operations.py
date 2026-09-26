# Source: ADR-1092 — port of the locally verified disk-hygiene implementation.
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import uuid

from cleanup_registry import Protected
from cleanup_processes import no_open_files


def run(argv, cwd=None):
    # Operational timeout, not a cleanup eligibility threshold.
    try:
        result = subprocess.run(
            argv, cwd=cwd, text=True, capture_output=True, timeout=30
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Protected(f"command unavailable: {argv[0]}: {exc}") from exc
    if result.returncode:
        raise Protected(
            f"{' '.join(argv[:3])}: {result.stderr.strip() or 'command failed'}"
        )
    return result.stdout.rstrip("\n")


def git(repo, *args):
    return run(["git", "-C", str(repo), *args])


def identity(path):
    p = Path(path)
    if p.is_symlink() or p.resolve() != p.absolute():
        raise Protected(f"symlink path: {path}")
    st = p.stat()
    return [st.st_dev, st.st_ino]


def trees(repo):
    records, item = [], {}
    for field in git(repo, "worktree", "list", "--porcelain", "-z").split("\0"):
        if not field:
            if item:
                records.append(item)
            item = {}
        else:
            key, _, value = field.partition(" ")
            item[key] = value
    return records


def linked(repo, path):
    listing = trees(repo)
    if not listing or str(Path(listing[0]["worktree"]).resolve()) != repo:
        raise Protected("repo must be the main checkout")
    if path == repo:
        raise Protected("main checkout is protected")
    found = next(
        (t for t in listing[1:] if str(Path(t["worktree"]).resolve()) == path), None
    )
    if not found or "branch" not in found or "locked" in found or "prunable" in found:
        raise Protected("not an available unlocked linked branch worktree")
    return found


def claim(state, path, owner, record):
    if path in state:
        raise Protected("path already registered; ownership cannot be reassigned")
    for other in (p for p in state if p != "_ended"):
        if Path(other) in Path(path).parents or Path(path) in Path(other).parents:
            raise Protected("overlapping registered paths")
    record.update(owner=owner, identity=identity(path))
    state[path] = record


def validate_pr(pr):
    if not re.fullmatch(
        r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/pull/[1-9][0-9]*", pr
    ):
        raise Protected("an explicit github.com PR URL is required")


def register_worktree(state, owner, path, details):
    repo, pr = details["repo"], details.get("pr")
    tree = linked(repo, path)
    if pr:
        validate_pr(pr)
    claim(
        state,
        path,
        owner,
        {"kind": "worktree", "repo": repo, "branch": tree["branch"], "pr": pr},
    )


def owned(state, owner, path):
    record = state.get(path)
    if not record or record["owner"] != owner:
        raise Protected("path is not owned by this host/session")
    if not record.get("pending_branch") and identity(path) != record["identity"]:
        raise Protected("registered directory was replaced")
    return record


def preserve(state, owner, path, evidence):
    record = owned(state, owner, path)
    evidence = Path(evidence)
    if any(
        Path(p) == evidence or Path(p) in evidence.parents
        for p in state
        if p != "_ended"
    ):
        raise Protected("evidence must be outside every disposable directory")
    identity(evidence)
    data = evidence.read_bytes()
    if not data:
        raise Protected("evidence must be a non-empty durable file")
    record["evidence"] = str(evidence)
    record["evidence_sha256"] = hashlib.sha256(data).hexdigest()
    if record["kind"] == "worktree":
        record["evidence_head"] = git(path, "rev-parse", "HEAD")


def evidence_ok(record):
    evidence = record.get("evidence")
    if not evidence:
        raise Protected("preserved evidence has not been explicitly marked")
    identity(evidence)
    if (
        hashlib.sha256(Path(evidence).read_bytes()).hexdigest()
        != record["evidence_sha256"]
    ):
        raise Protected("preserved evidence changed; mark it again")


def live_head(record):
    if not record.get("pr"):
        raise Protected("no PR linked yet")
    result = json.loads(
        run(
            ["gh", "pr", "view", record["pr"], "--json", "headRefOid,headRefName,url"],
            record["repo"],
        )
    )
    if (
        result.get("url") != record["pr"]
        or "refs/heads/" + result.get("headRefName", "") != record["branch"]
    ):
        raise Protected("PR identity or branch does not match registration")
    sha = result.get("headRefOid", "")
    if not re.fullmatch(r"[a-f0-9]{40,64}", sha):
        raise Protected("PR has no valid live head")
    return sha


def check_tree(path, record):
    if identity(path) != record["identity"]:
        raise Protected("registered directory was replaced")
    if linked(record["repo"], path)["branch"] != record["branch"]:
        raise Protected("worktree branch changed")
    # Include ignored files: they may hold credentials or unrecorded evidence.
    if git(path, "status", "--porcelain", "--untracked-files=all", "--ignored"):
        raise Protected("uncommitted, untracked or ignored files are present")
    head = git(path, "rev-parse", "HEAD")
    if head != record.get("evidence_head"):
        raise Protected("HEAD changed since evidence was preserved")
    return head


def dispose_tree(path, record, dry_run):
    evidence_ok(record)
    local = check_tree(path, record)
    remote = live_head(record)
    repo_url, number = record["pr"].split("/pull/")
    if dry_run:
        # A fetch writes objects/FETCH_HEAD; don't mutate the repository in dry-run.
        git(record["repo"], "cat-file", "-e", remote + "^{commit}")
    else:
        git(
            record["repo"],
            "fetch",
            "--no-tags",
            "--no-write-fetch-head",
            repo_url + ".git",
            "refs/pull/" + number + "/head",
        )
    git(record["repo"], "merge-base", "--is-ancestor", local, remote)
    # Recheck remote and local state after the network operation.
    if live_head(record) != remote or check_tree(path, record) != local:
        raise Protected("head changed during verification")
    if dry_run:
        return "would remove worktree and attempt safe local branch deletion"
    no_open_files(path)
    git(record["repo"], "worktree", "remove", path)
    if Path(path).exists() or any(t["worktree"] == path for t in trees(record["repo"])):
        raise Protected("Git did not remove the worktree")
    record["pending_branch"] = True
    return dispose_branch(path, record, False)


def dispose_branch(path, record, dry_run):
    evidence_ok(record)
    if Path(path).exists() or any(t["worktree"] == path for t in trees(record["repo"])):
        raise Protected("removed worktree path was recreated")
    local, remote = record["evidence_head"], live_head(record)
    git(record["repo"], "merge-base", "--is-ancestor", local, remote)
    if dry_run:
        return "would remove pending local branch"
    branch = record["branch"].removeprefix("refs/heads/")
    # Use the verified PR head as a command-local upstream. Git -d then checks
    # ancestry AND checked-out-elsewhere itself, including unmerged PR branches.
    # No persisted branch config changes and no -D or low-level branch deletion.
    proof_ref = "refs/disk-hygiene/" + uuid.uuid4().hex
    try:
        if git(record["repo"], "rev-parse", record["branch"]) != local:
            raise Protected("local branch advanced after worktree removal")
        if live_head(record) != remote:
            raise Protected("remote moved after worktree removal")
        git(record["repo"], "update-ref", proof_ref, remote, "")
        git(
            record["repo"],
            "-c",
            f"branch.{branch}.remote=.",
            "-c",
            f"branch.{branch}.merge={proof_ref}",
            "branch",
            "-d",
            "--",
            branch,
        )
    except Protected as exc:
        raise Protected(f"retained local branch {branch}: {exc}") from exc
    finally:
        if git(record["repo"], "for-each-ref", "--format=%(refname)", proof_ref):
            git(record["repo"], "update-ref", "-d", proof_ref, remote)
    return f"removed worktree and local branch {branch}"


def dispose_temp(path, record, dry_run):
    evidence_ok(record)
    # A nested Git repository may contain new commits even in disposable scratch.
    for _base, dirs, files in os.walk(path, followlinks=False):
        if ".git" in dirs or ".git" in files:
            raise Protected("temporary directory contains a Git checkout")
    if dry_run:
        return "would remove disposable temporary directory"
    no_open_files(path)
    if not shutil.rmtree.avoids_symlink_attacks:
        raise Protected("platform lacks symlink-safe directory removal")
    shutil.rmtree(path)
    return "removed disposable temporary directory"


def dispose(state, owner, selected=None, options=None):
    options = options or {}
    dry_run, temps = options.get("dry_run", False), options.get("temps", True)
    results = []
    targets = (
        [selected]
        if selected
        else [p for p, r in state.items() if p != "_ended" and r["owner"] == owner]
    )
    for path in targets:
        try:
            record = owned(state, owner, path)
            if record["kind"] == "temp" and not temps:
                continue
            handler = disposal_handler(record)
            message = handler(path, record, dry_run)
            results.append({"path": path, "status": message})
            if not dry_run:
                del state[path]
        except (Protected, OSError, ValueError, KeyError) as exc:
            results.append({"path": path, "protected": str(exc)})
    return results


def create_temp(state, owner, parent):
    identity(parent)
    listing = trees(str(Path.cwd()))
    repo = str(Path(listing[0]["worktree"]).resolve())
    path = tempfile.mkdtemp(prefix="disk-hygiene-", dir=parent)
    try:
        claim(state, path, owner, {"kind": "temp", "repo": repo})
    except Exception:
        os.rmdir(path)  # Newly created and still empty; never a fallback sweep.
        raise
    return {"created": path}


def disposal_handler(record):
    if record.get("pending_branch"):
        return dispose_branch
    return dispose_tree if record["kind"] == "worktree" else dispose_temp
