"""Static source-commit invariants of the shared Pipeline template.

Source: zetetic-team-subagents PR189 templates/ci/pipeline.yml, protected
workflow_run resolver and Record tested commit step (2026-10-23).
"""

from __future__ import annotations

# Source: contract checkout and downstream checkout refs in the shared template.
SOURCE_REF = "${{ github.sha }}"
POST_MERGE_REF = "${{ needs.resolve.outputs.tested_sha }}"
TESTED_REF = "${{ needs.contract.outputs.tested_sha }}"


def _steps(body: list[str]) -> list[list[str]]:
    steps: list[list[str]] = []
    for line in body:
        if line.startswith("      - "):
            steps.append(["    " + line[8:]])
        elif steps and line.startswith("        "):
            steps[-1].append(line[4:])
    return steps


def _required_step(body, field, identifier: str) -> list[str]:
    matches = [step for step in _steps(body) if field(step, "id") == identifier]
    return matches[0] if len(matches) == 1 else []


def _unconditional(step, field) -> bool:
    return (
        bool(step)
        and not field(step, "if")
        and field(step, "continue-on-error") in ("", "false")
    )


def _check_checkout(body, field, expected: str, job: str) -> list[str]:
    checkouts = [
        step
        for step in _steps(body)
        if field(step, "uses").startswith("actions/checkout@")
    ]
    if len(checkouts) != 1:
        return [f"{job} must have exactly one source checkout"]
    step = checkouts[0]
    refs = [line.strip() for line in step if line.startswith("      ref:")]
    failures = []
    if refs != [f"ref: {expected}"]:
        failures.append(f"{job} must check out {expected}")
    condition = "steps.guard.outputs.has_deploy_key == 'true'" if job == "tag" else ""
    if field(step, "if") != condition or field(step, "continue-on-error") not in (
        "",
        "false",
    ):
        failures.append(f"{job} checkout must retain its execution and failure policy")
    return failures


def _check_resolver(body, field) -> list[str]:
    failures = []
    outputs = field(body, "outputs")
    for name in ("tested_sha", "run_tests"):
        if f"{name}: ${{{{ steps.resolve.outputs.{name} }}}}" not in outputs:
            failures.append(f"resolve must bind its actual {name} output")
    if not _unconditional(_required_step(body, field, "resolve"), field):
        failures.append(
            "resolve must execute its protected merge step without ignoring failure"
        )
    return failures


def _check_receipt(body, field) -> list[str]:
    """Require the source run and exact direct-job results, including every OS."""
    run = field(_required_step(body, field, "resolve"), "run")
    clauses = (
        'run.get("path") == ".github/workflows/pipeline.yml" '
        'and run.get("name") == "Pipeline"',
        'required = ["contract", "unit", "regression", "e2e", "review", "merge"]',
        'for category in ("environment", "install"):',
        'for runner in ("ubuntu-latest", "macos-latest", "windows-latest")',
        "len(actual) == len(expected) and set(actual) == expected",
        "len(matching) == 1,",
        'allowed = job.get("conclusion") == "success"',
        'job.get("status") == "completed" and allowed,',
        "_validate_run(source, repository)",
        "_validate_run(run, repository)",
        '_validate_jobs(jobs, run.get("actor", {}).get("login"))',
    )
    if any(clause not in run for clause in clauses):
        return [
            "resolve must require the direct Pipeline receipt and exact job results"
        ]
    return []


def _check_record(body, field, source_ref: str) -> list[str]:
    step = _required_step(body, field, "source")
    failures = []
    if not _unconditional(step, field):
        failures.append("contract must unconditionally verify the checked-out SHA")
    if field(step, "env") != f"EXPECTED_SHA: {source_ref}":
        failures.append("contract must verify the resolved source SHA")
    expected_run = (
        'actual="$(git rev-parse HEAD)" test "$actual" = "$EXPECTED_SHA" '
        'echo "tested_sha=$actual" >> "$GITHUB_OUTPUT"'
    )
    if field(step, "run") != expected_run:
        failures.append("contract must record the verified actual checkout SHA")
    if "tested_sha: ${{ steps.source.outputs.tested_sha }}" not in field(
        body, "outputs"
    ):
        failures.append("contract must expose the verified checkout SHA")
    return failures


def _check_merge_confirmation(body, field) -> list[str]:
    """Pin the post-PUT identity and main ancestry checks in the resolver."""
    run = field(_required_step(body, field, "resolve"), "run")
    clauses = (
        'pr = api.request("GET", pr_path)',
        '_pr_identity(pr, repository, original_pr["head"]["sha"])',
        'require( pr.get("merged") is True and pr.get("merge_commit_sha") == sha,',
        '"GET", f"/repos/{repository}/compare/main...{full_sha(sha)}"',
        'require( comparison.get("status") in ("behind", "identical") '
        'and comparison.get("merge_base_commit", {}).get("sha") == sha,',
        "_confirm_main_merge(pr_path, pr, sha, api) if already_merged "
        "and _has_push_pipeline(repository, sha, api):",
    )
    if any(clause not in run for clause in clauses):
        return ["resolve must confirm the merged PR identity and main ancestry"]
    return []


def _check_release(body, field) -> list[str]:
    """Keep publication on trusted code while explicitly targeting the tested SHA."""
    step = _required_step(body, field, "publish")
    failures = []
    if field(step, "if") != "steps.guard.outputs.has_deploy_key == 'true'" or field(
        step, "continue-on-error"
    ) not in ("", "false"):
        failures.append("tag publication must retain its execution and failure policy")
    expected_env = (
        "RELEASE_TAGS: ${{ needs.contract.outputs.release_tags }} "
        f"TESTED_SHA: {TESTED_REF}"
    )
    if field(step, "env") != expected_env:
        failures.append("tag must bind the tested SHA and declared release tags")
    run = field(step, "run")
    clauses = (
        'sha = os.environ["TESTED_SHA"] validate(tags, sha) '
        "published, existing = publish(tags, sha)",
        'git("cat-file", "-t", sha).stdout.strip() != "commit"',
        '"rev-parse", "--verify", "refs/remotes/origin/main^{commit}"',
        'if git("rev-parse", "HEAD").stdout.strip() != trusted: raise ValueError(',
        'git("merge-base", "--is-ancestor", sha, trusted)',
        '"tag", "-a", "-m", "Release " + tag, "--", tag, sha,',
    )
    if any(clause not in run for clause in clauses):
        failures.append(
            "tag must verify main ancestry and publish the explicit tested SHA"
        )
    return failures


def check_sources(bodies, field, test_jobs, post_merge=False) -> list[str]:
    """Check producer output bindings, verification, and every consumer checkout."""
    failures = []
    source_ref = POST_MERGE_REF if post_merge else SOURCE_REF
    if post_merge:
        failures += _check_resolver(bodies.get("resolve", []), field)
        failures += _check_merge_confirmation(bodies.get("resolve", []), field)
        failures += _check_receipt(bodies.get("resolve", []), field)
    failures += _check_record(bodies.get("contract", []), field, source_ref)
    failures += _check_release(bodies.get("tag", []), field)
    for job in ("contract", *test_jobs, "tag"):
        expected = source_ref if job == "contract" else TESTED_REF
        if job == "tag":
            expected = "main"
        failures += _check_checkout(bodies.get(job, []), field, expected, job)
    return failures
