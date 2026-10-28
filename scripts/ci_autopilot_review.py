"""Resume trusted review-only gates locally without extra model calls.

Source: ci_codex_review_event.resume and resumption_plan are the existing
server-revalidated contracts. This helper neither fabricates events nor
executes candidate code. Python -I isolates the per-PR EXPECTED_PR binding.
"""

import json
import os
from pathlib import Path
import subprocess
import sys


def reconcile(options, item):
    done = subprocess.run(
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
        check=True,
    )
    result = json.loads(done.stdout)
    if not isinstance(result, dict) or result.get("action") not in (
        "none",
        "repair",
        "review",
        "merge",
    ):
        raise RuntimeError("Review reconciliation returned invalid evidence")
    diagnostic(options, item, result)
    return result


def diagnostic(options, item, result):
    reason = result.get("reason")
    target = f"{options.repository}#{item['number']}"
    if reason == "evidence_unverifiable":
        print(f"autopilot review: unverifiable proof {target}", file=sys.stderr)
    elif reason == "review_infrastructure":
        print(f"autopilot review: infrastructure repair {target}", file=sys.stderr)


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
        return {"action": "none", "reason": "evidence_unverifiable"}
    if (
        proof.get("reviews_complete") is True
        and proof.get("reason") == "review_unresolved"
    ):
        if event.source.latest(args.repo, args.sha, args.pr) is None:
            return {"action": "none"}
        return {"action": "repair"}
    if proof.get("state") != "success" or proof.get("reviews_complete") is not True:
        return {"action": "none"}
    result = event.resume(
        args.repo, {"number": args.pr, "sha": args.sha, "run_id": None}
    )
    return (
        repair_after_noop(args, event, reader, proof)
        if result["action"] == "none"
        else result
    )


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
    except reader.runtime.EvidenceError:
        print("autopilot review: unverifiable evidence", file=sys.stderr)
        print(json.dumps({"action": "none", "reason": "evidence_unverifiable"}))
        return 0


if __name__ == "__main__":
    sys.exit(main())
