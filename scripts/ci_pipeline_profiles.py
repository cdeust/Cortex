"""Explicit direct and post-merge job contracts; never inferred from input YAML.

Source: zetetic-team-subagents PR189 separated-events design (2026-10-24).
"""

from __future__ import annotations

# Source: the canonical shared Pipeline's five test categories.
TEST_JOBS = ("unit", "regression", "e2e", "environment", "install")
REQUIRED_RESULTS = ("contract", *TEST_JOBS)
DIRECT_NEEDS = {
    "contract": (),
    "unit": ("contract",),
    "regression": ("contract", "unit"),
    "e2e": ("contract", "regression"),
    "environment": ("contract", "e2e"),
    "install": ("contract", "environment"),
    "review": TEST_JOBS,
    "merge": (*REQUIRED_RESULTS, "review"),
    "tag": REQUIRED_RESULTS,
}
POST_MERGE_NEEDS = {
    "resolve": (),
    **{
        job: needs
        for job, needs in DIRECT_NEEDS.items()
        if job not in ("review", "merge")
    },
    "contract": ("resolve",),
}
# Source: existing same-repository, non-draft PR review and merge policy.
PR_CONDITION = (
    "always() && !cancelled() && github.event_name == 'pull_request' "
    "&& !github.event.pull_request.draft "
    "&& github.event.pull_request.head.repo.full_name == github.repository"
)
RESOLVE_CONDITION = (
    "github.event_name == 'workflow_run' "
    "&& github.event.workflow_run.event == 'pull_request' "
    "&& github.event.workflow_run.conclusion == 'success'"
)


def conditions(post_merge: bool) -> dict[str, str]:
    """Require all category results and the event appropriate to each engine."""
    needs = POST_MERGE_NEEDS if post_merge else DIRECT_NEEDS
    result = {
        job: "!cancelled()"
        + "".join(f" && needs.{dep}.result == 'success'" for dep in needs[job])
        for job in TEST_JOBS
    }
    if post_merge:
        result.update(
            resolve=RESOLVE_CONDITION,
            contract="!cancelled() && github.event_name == 'workflow_run' "
            "&& needs.resolve.result == 'success' "
            "&& needs.resolve.outputs.run_tests == 'true'",
            tag="!cancelled() && github.event_name == 'workflow_run'",
        )
    else:
        result.update(
            contract="!cancelled()",
            review=PR_CONDITION,
            merge=PR_CONDITION,
            tag="!cancelled() && github.event_name == 'push' "
            "&& github.ref == 'refs/heads/main'",
        )
    result["tag"] += "".join(
        f" && needs.{job}.result == 'success'" for job in REQUIRED_RESULTS
    )
    return result
