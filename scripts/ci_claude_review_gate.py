#!/usr/bin/env python3
"""Read whether main requires claude[bot] reviews: the activation trust anchor.

main's .github/workflows/claude.yml declares `CLAUDE_REVIEW_GATE: observe` or
`required`. A PR cannot change main, so the gate is read from main only. An
absent file or observe means Codex-only; a declaration this reader cannot
classify fails loudly instead of silently disabling the gate.
Sources: https://docs.github.com/en/rest/repos/contents#get-repository-content
Self-contained on purpose: pipeline.yml embeds this exact file under python3 -I.
source: ADR-1116
"""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

GATE = re.compile(r"\s*CLAUDE_REVIEW_GATE:(.*)")
WORKFLOWS = ".github/workflows"
REPO_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_.-]+")


class EvidenceError(ValueError):
    """Only fixed diagnostic categories may cross the CLI boundary."""


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise EvidenceError("arguments")


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in items:
        if key in value:
            raise EvidenceError("protocol")
        value[key] = item
    return value


def _api(endpoint: str) -> Any:
    # https://cli.github.com/manual/gh_api
    try:
        done = subprocess.run(
            ["gh", "api", endpoint], text=True, capture_output=True, check=True
        )
        return json.loads(done.stdout, object_pairs_hook=_pairs)
    except (OSError, subprocess.SubprocessError) as exc:
        raise EvidenceError("api") from exc
    except ValueError as exc:
        raise EvidenceError("protocol") from exc


def declares_required(text: str) -> bool:
    """True only when the workflow text declares the review gate required."""
    values = [m.group(1) for m in map(GATE.fullmatch, text.splitlines()) if m]
    if len(values) > 1 or any(v not in (" observe", " required") for v in values):
        raise EvidenceError("protocol")
    return values == [" required"]


def main_requires_claude(repo: str, api: Any = None) -> bool:
    """Read main's claude.yml; the listing makes absence an answer, not an error."""
    call = _api if api is None else api
    listing = call(f"repos/{repo}/contents/{WORKFLOWS}?ref=main")
    if not isinstance(listing, list) or any(
        not isinstance(entry, dict) or not isinstance(entry.get("name"), str)
        for entry in listing
    ):
        raise EvidenceError("protocol")
    entries = [entry for entry in listing if entry["name"] == "claude.yml"]
    if not entries:
        return False
    if len(entries) != 1 or entries[0].get("type") != "file":
        raise EvidenceError("protocol")
    record = call(f"repos/{repo}/contents/{WORKFLOWS}/claude.yml?ref=main")
    if (
        not isinstance(record, dict)
        or record.get("encoding") != "base64"
        or not isinstance(record.get("content"), str)
    ):
        raise EvidenceError("protocol")
    try:
        raw = base64.b64decode("".join(record["content"].split()), validate=True)
        return declares_required(raw.decode("utf-8"))
    except (binascii.Error, UnicodeDecodeError) as exc:
        raise EvidenceError("protocol") from exc


def main(argv: list[str] | None = None) -> int:
    try:
        parser = Parser(description=__doc__)
        parser.add_argument("--repo", required=True)
        parser.add_argument("--github-output", action="store_true")
        args = parser.parse_args(argv)
        if REPO_PATTERN.fullmatch(args.repo) is None or args.repo.split("/")[1] in (
            ".",
            "..",
        ):
            raise EvidenceError("arguments")
        required = main_requires_claude(args.repo)
        if args.github_output:
            output = os.environ.get("GITHUB_OUTPUT", "")
            with Path(output).open("a", encoding="utf-8") as stream:
                stream.write(f"required={str(required).lower()}\n")
        print(json.dumps({"required": required}))
        return 0
    except OSError:
        print("claude gate: output", file=sys.stderr)
        return 1
    except EvidenceError as exc:
        print(f"claude gate: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
