"""Classify local repairs while GitHub alone issues native gate reruns.

Source: ci_codex_review_event_source and resumption_plan are existing trusted
read-only contracts. Cortex PR #816 Claude reviews 6458968789 and 6459888424
identified rerun races and per-PR helper failures. The child environment binds
EXPECTED_PR; Python -I ignores PYTHON* variables and the user site.
"""

import json
import os
from pathlib import Path
import subprocess
import sys


def invoke_child(options, item):
    return subprocess.run(
        [
            sys.executable,
            "-I",
            "-B",
            str(Path(__file__).resolve()),
            "--repo",
            options.repository,
            "--pr",
            str(item["number"]),
            "--sha",
            item["sha"],
        ],
        cwd=options.repo,
        env={**os.environ, "EXPECTED_PR": str(item["number"])},
        capture_output=True,
        text=True,
        check=False,
    )


def helper_failure(category, exit_code=None):
    result = {"action": "none", "reason": "helper_failure", "category": category}
    if exit_code is not None:
        result["exit_code"] = exit_code
    return result


def decode_result(output):
    try:
        result = json.loads(output)
    except json.JSONDecodeError:
        return helper_failure("protocol")
    if not isinstance(result, dict) or result.get("action") not in (
        "none",
        "repair",
    ):
        return helper_failure("protocol")
    if result.get("reason") not in (
        None,
        "evidence_unverifiable",
        "review_infrastructure",
    ):
        return helper_failure("protocol")
    if (
        result.get("reason") == "evidence_unverifiable" and result["action"] != "none"
    ) or (
        result.get("reason") == "review_infrastructure" and result["action"] != "repair"
    ):
        return helper_failure("protocol")
    if ("category" in result or result.get("reason") == "evidence_unverifiable") and (
        result.get("category") not in ("api", "protocol", "environment", "eligibility")
    ):
        return helper_failure("protocol")
    return result


def reconcile(options, item):
    try:
        done = invoke_child(options, item)
    except OSError:
        result = helper_failure("environment")
    else:
        result = (
            helper_failure("environment", done.returncode)
            if done.returncode
            else decode_result(done.stdout)
        )
    diagnostic(options, item, result)
    return result


def diagnostic(options, item, result):
    reason = result.get("reason")
    target = f"{options.repository}#{item['number']}"
    if reason == "evidence_unverifiable":
        category = result.get("category")
        if category not in ("api", "protocol", "environment", "eligibility"):
            raise RuntimeError("Review helper diagnostic contract is invalid")
        print(
            f"autopilot review: {category} evidence unavailable {target}",
            file=sys.stderr,
        )
    elif reason == "review_infrastructure":
        print(f"autopilot review: infrastructure repair {target}", file=sys.stderr)
    elif reason == "helper_failure":
        code = f" exit_code={result['exit_code']}" if "exit_code" in result else ""
        print(
            f"autopilot review: helper_failure {result['category']}{code} {target}",
            file=sys.stderr,
        )


def unavailable(reason):
    if reason in ("api", "environment"):
        category = reason
    elif reason == "arguments":
        category = "environment"
    elif reason in ("head_moved", "pr_eligibility"):
        category = "eligibility"
    else:
        category = "protocol"
    return {"action": "none", "reason": "evidence_unverifiable", "category": category}


def check(args, event, reader):
    # Eligibility includes open/non-draft/same-repo/current SHA and owner holds.
    if event.source.live_pr(args.repo, args.pr, args.sha) is None:
        return {"action": "none"}
    proof = reader._fetch(args)
    if proof.get("sha") != args.sha:
        return {"action": "none"}
    if proof.get("reason") not in (
        "review_missing",
        "review_pending",
        "review_failed",
        "review_unresolved",
        "reviews_complete",
    ):
        return unavailable(proof.get("reason"))
    if (
        proof.get("reviews_complete") is True
        and proof.get("reason") == "review_unresolved"
    ):
        if event.source.latest(args.repo, args.sha, args.pr) is None:
            return {"action": "none"}
        return {"action": "repair"}
    if proof.get("state") != "success" or proof.get("reviews_complete") is not True:
        return {"action": "none"}
    # A ready native plan waits for GitHub's serialized rerun issuer.
    return repair_after_noop(args, event, reader, proof)


def infrastructure_failure(indexed, policy):
    if indexed is None or not policy._repair_dependencies(indexed):
        return False
    review = indexed.get("review", {})
    return (
        review.get("conclusion") == "failure"
        and not policy._waited(review, policy.READINESS)
        and all(policy._success(indexed.get(name, {})) for name in policy.PREREQUISITES)
        and all(
            policy._success(job) or job.get("conclusion") == "skipped"
            for name, job in indexed.items()
            if name not in ("review", "merge")
        )
    )


def repair_after_noop(args, event, reader, proof):
    # -I's entry point binds the trusted sibling directory before this import.
    import ci_codex_review_resume as policy  # noqa: PLC0415

    run = event.source.latest(args.repo, args.sha, args.pr)
    if run is None:
        return {"action": "none"}
    jobs = event._jobs(args.repo, run)
    if (
        not policy._complete_inputs(run, jobs, proof, args.sha)
        or event._plan(run, jobs, proof, args.sha)["action"] != "none"
        or not infrastructure_failure(policy._index(jobs), policy)
    ):
        return {"action": "none"}
    current = event.source.latest(args.repo, args.sha, args.pr)
    if (
        current is None
        or any(current[key] != run[key] for key in ("id", "run_attempt"))
        or event.source.live_pr(args.repo, args.pr, args.sha) is None
        or reader._fetch(args) != proof
    ):
        return {"action": "none"}
    return {"action": "repair", "reason": "review_infrastructure"}


def main():
    # All loaded modules are adjacent reviewed installation assets, never PR data.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import ci_codex_review_event as event  # noqa: PLC0415
    import ci_codex_reviews as reader  # noqa: PLC0415

    try:
        args = reader._arguments(None)
        if os.environ.get("EXPECTED_PR") != str(args.pr):
            raise reader.EvidenceError("environment")
        print(json.dumps(check(args, event, reader)))
        return 0
    except reader.runtime.EvidenceError as exc:
        result = unavailable(str(exc))
        print(
            f"autopilot review: {result['category']} evidence unavailable",
            file=sys.stderr,
        )
        print(json.dumps(result))
        return 0


if __name__ == "__main__":
    sys.exit(main())
