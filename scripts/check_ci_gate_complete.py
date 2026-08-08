"""CI-gate completeness: every ci.yml job must be behind the aggregate gate.

Branch protection on ``main`` names required status checks as strings, in
GitHub settings — outside git, invisible in review, and unversioned. Naming
individual jobs there makes the contract break on every rename: extracting
the test steps into a reusable workflow (issue #336) renamed the four matrix
legs to ``Test (Python X.Y) / Test (Python X.Y)``, so the four bare contexts
``main`` required were never reported again and a fully green PR sat BLOCKED
(PR #387, run 31250898534). Renaming the contexts fixes that one PR and
leaves the next rename to rediscover it.

So protection names ONE ci.yml context — ``CI Green`` — and the real list
lives here, in git, where a diff shows it. That moves the failure mode: the
gate is only as good as its ``needs:`` list, and a job added later that
nobody adds to it is silently ungated. That is what this script refuses.

It also refuses the second escape hatch. The gate treats any result other
than ``success`` as failure, EXCEPT for jobs named in its ``ALLOWED_SKIPS``
env — because a job carrying a job-level ``if:`` legitimately reports
``skipped``. An unlisted conditional would therefore let a job skip its way
past the gate, so every job with an ``if:`` must be declared, and every
declared exemption must correspond to a job that actually has one (a stale
exemption is a hole nobody is watching).

Checks, all of them fatal:

1. the gate job exists;
2. every other ci.yml job appears in the gate's ``needs:``;
3. every name in ``needs:`` is a real job;
4. every job carrying a job-level ``if:`` is listed in ``ALLOWED_SKIPS``;
5. every name in ``ALLOWED_SKIPS`` is a job that carries an ``if:``.

Static only — regex over the workflow text, no PyYAML. The Lint job installs
ruff and nothing else, and this script runs there alongside
``check_doc_claims.py``, which is static for the same reason.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"

# The single job branch protection points at. Renaming it is a protection
# change, not a refactor — hence a named constant rather than a literal.
GATE_JOB = "ci-green"

_JOB_RE = re.compile(r"^  ([A-Za-z0-9_-]+):\s*$")
_JOB_IF_RE = re.compile(r"^    if:\s*(\S.*)$")
_NEEDS_BLOCK_RE = re.compile(r"^    needs:\s*$")
_NEEDS_ITEM_RE = re.compile(r"^      - ([A-Za-z0-9_-]+)\s*$")
_ALLOWED_SKIPS_RE = re.compile(r"^\s*ALLOWED_SKIPS:\s*(\S.*?)\s*$")


# Shortest string that can carry a matched quote pair: the two quotes.
_QUOTED_MIN_LEN = 2


def _strip_quotes(value: str) -> str:
    if len(value) >= _QUOTED_MIN_LEN and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def _job_bodies(text: str) -> dict[str, list[str]]:
    """Return job id -> the lines of its block, in file order."""
    bodies: dict[str, list[str]] = {}
    in_jobs = False
    current: str | None = None

    for line in text.splitlines():
        if line.startswith("jobs:"):
            in_jobs = True
            continue
        if not in_jobs:
            continue
        # A new top-level key (indent 0) ends the jobs mapping.
        if line and not line.startswith(" ") and not line.startswith("#"):
            break
        job_match = _JOB_RE.match(line)
        if job_match:
            current = job_match.group(1)
            bodies[current] = []
            continue
        if current is not None:
            bodies[current].append(line)

    return bodies


def _parse_needs(body: list[str]) -> list[str]:
    """Return the job ids listed under this block's ``needs:`` sequence."""
    needs: list[str] = []
    collecting = False

    for line in body:
        if _NEEDS_BLOCK_RE.match(line):
            collecting = True
            continue
        if not collecting:
            continue
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        item = _NEEDS_ITEM_RE.match(line)
        if not item:
            collecting = False
            continue
        needs.append(item.group(1))

    return needs


def _parse_allowed_skips(body: list[str]) -> list[str]:
    """Return the job ids named by this block's ``ALLOWED_SKIPS`` env."""
    for line in body:
        match = _ALLOWED_SKIPS_RE.match(line)
        if match is None:
            continue
        raw = _strip_quotes(match.group(1))
        return [name.strip() for name in raw.split(",") if name.strip()]
    return []


def parse_workflow(text: str) -> tuple[dict[str, bool], list[str], list[str]]:
    """Return (job_id -> has job-level ``if:``, gate needs, allowed skips).

    Pre:  ``text`` is the ci.yml source.
    Post: jobs are the top-level keys under ``jobs:`` (indent 2); needs and
          allowed-skips are read from the gate job's block only.
    """
    bodies = _job_bodies(text)
    jobs = {
        job: any(_JOB_IF_RE.match(line) for line in body)
        for job, body in bodies.items()
    }
    gate_body = bodies.get(GATE_JOB, [])
    return jobs, _parse_needs(gate_body), _parse_allowed_skips(gate_body)


def check(text: str) -> list[str]:
    """Return the list of failures; empty means the gate is complete."""
    jobs, needs, allowed_skips = parse_workflow(text)
    failures: list[str] = []

    if GATE_JOB not in jobs:
        return [
            f"job '{GATE_JOB}' is missing from ci.yml — branch protection "
            f"requires its status check, so main would block on a context "
            f"nothing reports"
        ]

    gated = set(needs)
    for job, _ in sorted(jobs.items()):
        if job == GATE_JOB:
            continue
        if job not in gated:
            failures.append(
                f"job '{job}' is not in {GATE_JOB}.needs — it would run "
                f"outside the gate and could fail without blocking a merge"
            )

    for name in needs:
        if name not in jobs:
            failures.append(
                f"{GATE_JOB}.needs lists '{name}', which is not a job in ci.yml"
            )

    conditional = {job for job, has_if in jobs.items() if has_if and job != GATE_JOB}
    for job in sorted(conditional - set(allowed_skips)):
        failures.append(
            f"job '{job}' carries a job-level 'if:' but is not in "
            f"ALLOWED_SKIPS — it can report 'skipped' and slip past the gate. "
            f"Declare it (with the reason) or drop the condition"
        )
    for name in sorted(set(allowed_skips) - conditional):
        failures.append(
            f"ALLOWED_SKIPS lists '{name}', which has no job-level 'if:' in "
            f"ci.yml — a stale exemption lets a real skip go unnoticed"
        )

    return failures


def main() -> int:
    if not CI_WORKFLOW.exists():
        print(f"FAIL: {CI_WORKFLOW} not found", file=sys.stderr)
        return 1

    failures = check(CI_WORKFLOW.read_text(encoding="utf-8"))
    if failures:
        print("CI gate completeness: FAIL", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1

    print("CI gate completeness: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
