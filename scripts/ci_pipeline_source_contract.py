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
    if field(step, "if") != "" or field(step, "continue-on-error") not in (
        "",
        "false",
    ):
        failures.append(f"{job} checkout must retain its execution and failure policy")
    return failures


def _check_fetch(body, field, job: str) -> list[str]:
    """The tag job fetches the tested SHA into a bare repository and checks nothing out.

    Source: zetetic-team-subagents PR237 (CodeQL actions/untrusted-checkout on
    Cortex PR839: a checkout under the write-enabled deploy key after workflow_run).
    """
    steps = _steps(body)
    if any(field(step, "uses").startswith("actions/checkout@") for step in steps):
        return [f"{job} must not check out any commit under the deploy key"]
    fetches = [
        step
        for step in steps
        if field(step, "name") == "Fetch the tested commit into a bare repository"
    ]
    if len(fetches) != 1:
        return [f"{job} must have exactly one bare fetch of the tested commit"]
    step = fetches[0]
    failures = []
    env = field(step, "env")
    key = "SSH_KEY: ${{ secrets.RELEASE_TAG_SSH_KEY }}"
    if f"TESTED_SHA: {TESTED_REF}" not in env or key not in env:
        failures.append(f"{job} fetch must bind the tested SHA and the deploy key")
    run = field(step, "run")
    for clause in (
        "git init --quiet --bare",
        'fetch --quiet --depth=1 origin "$TESTED_SHA"',
        "StrictHostKeyChecking=yes",
    ):
        if clause not in run:
            failures.append(f"{job} fetch must stay bare, by SHA and host-key checked")
            break
    if field(step, "if") != "steps.guard.outputs.has_deploy_key == 'true'" or field(
        step, "continue-on-error"
    ) not in ("", "false"):
        failures.append(f"{job} fetch must retain its execution and failure policy")
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
    """Require the source run and exact direct-job results: every OS, or Linux
    alone for a pull request the resolver finds documentation only (ADR-1133)."""
    run = field(_required_step(body, field, "resolve"), "run")
    clauses = (
        'run.get("path") == ".github/workflows/pipeline.yml" '
        'and run.get("name") == "Pipeline"',
        'required = ["contract", "unit", "regression", "e2e", "merge"]',
        'for category in ("environment", "install"):',
        'RUNNERS = ("ubuntu-latest", "macos-latest", "windows-latest")',
        'full = {f"{category} ({runner})" for runner in RUNNERS}',
        'linux = {f"{category} ({RUNNERS[0]})"}',
        "len(actual) == len(set(actual)) and set(actual) in (full, linux),",
        "len(shapes) == 1,",
        "return shapes == {1}",
        "len(matching) == 1,",
        'allowed = job.get("conclusion") == "success"',
        'job.get("status") == "completed" and allowed,',
        "_validate_run(source, repository)",
        "_validate_run(run, repository)",
        'run["reduced_matrix"] = _validate_jobs(jobs) return run',
        'if run.get("reduced_matrix"): require( '
        "_documentation_only(pr, repository, api),",
        "return len(paths) < FILES_LISTED_AT_MOST and documentation_only(",
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
    """Pin the post-PUT identity checks in the resolver.

    The PR is re-read; main is never compared.
    """
    run = field(_required_step(body, field, "resolve"), "run")
    clauses = (
        'pr = api.request("GET", pr_path)',
        '_pr_identity(pr, repository, original_pr["head"]["sha"])',
        'require( pr.get("merged") is True and pr.get("merge_commit_sha") == sha,',
        "_confirm_pr_merge(pr_path, pr, sha, api) if already_merged "
        "and _has_push_pipeline(repository, sha, api):",
    )
    if any(clause not in run for clause in clauses):
        return ["resolve must confirm the merged PR identity"]
    return []


def _check_release(body, field) -> list[str]:
    """Publish the tags on the explicitly tested SHA.

    That SHA is the commit the push event built.
    """
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
        '"tag", "-a", "-m", "Release " + tag, "--", tag, sha,',
    )
    if any(clause not in run for clause in clauses):
        failures.append("tag must publish the explicit tested SHA")
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
    for job in ("contract", *test_jobs):
        expected = source_ref if job == "contract" else TESTED_REF
        failures += _check_checkout(bodies.get(job, []), field, expected, job)
    failures += _check_fetch(bodies.get("tag", []), field, "tag")
    return failures
