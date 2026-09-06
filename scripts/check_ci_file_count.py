"""Refuse PR path classification when GitHub's file list may be incomplete."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys


# source: https://docs.github.com/en/rest/pulls/pulls#list-pull-requests-files
# The REST endpoint used by dorny/paths-filter returns at most 3000 files.
API_FILE_LIMIT = 3000


def check(count: object) -> str | None:
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        return "pull_request.changed_files must be a nonnegative integer"
    if count > API_FILE_LIMIT:
        return (
            f"PR changes {count} files, exceeding GitHub's {API_FILE_LIMIT}-file "
            "API limit; refusing incomplete classification. Split the PR."
        )
    return None


def main() -> int:
    try:
        event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
        failure = check(event["pull_request"].get("changed_files"))
    except (KeyError, OSError, ValueError, TypeError, AttributeError) as error:
        failure = f"cannot validate pull request file count: {error}"
    if failure:
        print(f"::error::{failure}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
