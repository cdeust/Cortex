"""One maintainer-owned progress comment, requested for Cortex PR776.

Source: GitHub REST issue comments create/update endpoints. These comments
report dispatch state; they never constitute native review or test evidence.
"""

import subprocess
import sys

# source: Cortex PR776 comment6437044487; stable maintainer-owned upsert marker.
MARKER = "<!-- cortex-autopilot-status -->"


def publish(options, github, item: dict, phase: str) -> None:
    if not getattr(options, "status_comments", False):
        return
    if item.get("announced_phase") == phase:
        return
    try:
        _publish(options, github, item, phase)
        item["announced_phase"] = phase
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        # Visibility failures must not block actual repair or accepted settlement.
        print(f"Autopilot status comment failed: {type(exc).__name__}", file=sys.stderr)


def _publish(options, github, item: dict, phase: str) -> None:
    repo, number = options.repository, item["number"]
    actor = github(options, "api", "user")["login"]
    endpoint = f"repos/{repo}/issues/{number}/comments"
    pages = github(options, "api", "--paginate", "--slurp", endpoint)
    comments = [row for page in pages for row in page]
    existing = next(
        (
            row
            for row in comments
            if isinstance(row.get("user"), dict)
            and row["user"].get("login") == actor
            and MARKER in (row.get("body") or "")
        ),
        None,
    )
    body = f"{MARKER}\nLocal Codex CLI maintenance, via the maintainer account.\n\n"
    body += (
        "Worker dispatched." if phase == "dispatched" else f"Worker reported: {phase}."
    )
    if item["kind"] == "pull":
        head = github(
            options, "pr", "view", str(number), "--repo", repo, "--json", "headRefOid"
        )["headRefOid"]
        body += f"\n\nCurrent remote head: `{head}`. [Hosted checks](https://github.com/{repo}/pull/{number}/checks)."
    body += "\n\nThis status is separate from native Codex review and CI results."
    if existing and existing.get("body") == body:
        return
    if existing:
        endpoint = f"repos/{repo}/issues/comments/{existing['id']}"
    github(
        options,
        "api",
        "--method",
        "PATCH" if existing else "POST",
        endpoint,
        "-f",
        f"body={body}",
    )
