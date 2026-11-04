# source: https://github.com/cdeust/Cortex/blob/f4831d159c181b5e170c984f703ed733819f188e/tests_py/scripts/test_ci_codex_review_resume.py
"""A completion event resumes only the gate that waited for its evidence."""

import importlib.util
from pathlib import Path
import unittest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/ci_codex_review_resume.py"
SHA = "a" * 40  # GitHub SHA-1 field, synthetic fixture.


def load_policy():
    spec = importlib.util.spec_from_file_location("resume_policy", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run():
    return {"status": "completed", "conclusion": "failure", "head_sha": SHA}


def jobs():
    # Source: pipeline.yml jobs and OS matrix; IDs are opaque fixture identities.
    names = ["contract", "unit", "regression", "e2e"] + [
        f"{kind} ({os})"
        for kind in ("environment", "install")
        for os in ("ubuntu-latest", "macos-latest", "windows-latest")
    ]
    result = [
        {"id": index + 1, "name": name, "status": "completed", "conclusion": "success"}
        for index, name in enumerate(names)
    ]
    result.extend(
        [
            {
                "id": 20,
                "name": "review",
                "status": "completed",
                "conclusion": "success",
            },
            {
                "id": 21,
                "name": "merge",
                "status": "completed",
                "conclusion": "failure",
                "steps": [
                    {"name": "Require complete Codex reviews", "conclusion": "failure"}
                ],
            },
        ]
    )
    return result


def evidence(state="success"):
    return {
        "state": state,
        "reason": "review_unresolved" if state == "blocked" else "reviews_complete",
        "sha": SHA,
        "reviews_complete": True,
    }


def waiting_jobs():
    current = jobs()
    current[-2].update(
        conclusion="failure",
        steps=[
            {
                "name": "Require completed Codex reviews",
                "conclusion": "failure",
            }
        ],
    )
    current[-1]["steps"] = [
        {"name": "Require completed tests and review", "conclusion": "failure"}
    ]
    return current


class ResumePolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy = load_policy()

    def plan(self, *, source=None, job_list=None, proof=None):
        return self.policy.resumption_plan(
            run() if source is None else source,
            jobs() if job_list is None else job_list,
            evidence() if proof is None else proof,
            SHA,
        )

    def test_clean_complete_reviews_resume_failed_merge_only(self):
        self.assertEqual(self.plan(), {"action": "merge", "job_id": 21})

    def test_clean_completion_resumes_green_pipeline_that_waited_for_review(self):
        current = jobs()
        current[-1].update(name="merge pending review", conclusion="success", steps=[])
        source = {**run(), "conclusion": "success"}
        self.assertEqual(
            self.plan(source=source, job_list=current),
            {"action": "review", "job_id": 20},
        )

    def test_complete_reviews_resume_readiness_for_fix_even_with_findings(self):
        for state in ("success", "blocked"):
            self.assertEqual(
                self.plan(job_list=waiting_jobs(), proof=evidence(state)),
                {"action": "review", "job_id": 20},
            )

    def test_late_reviews_resume_failed_tests_for_repair(self):
        current = waiting_jobs()
        current[1]["conclusion"] = "failure"
        for job in current[2:-2]:
            job["conclusion"] = "skipped"
        self.assertEqual(
            self.plan(job_list=current), {"action": "review", "job_id": 20}
        )

    def test_unexpanded_skipped_matrices_still_allow_failed_test_repair(self):
        current = waiting_jobs()
        current[1]["conclusion"] = "failure"
        current = [
            j
            for j in current
            if not j["name"].startswith(("environment (", "install ("))
        ]
        for identity, name in enumerate(("environment", "install"), start=30):
            current.append(
                {
                    "id": identity,
                    "name": name,
                    "status": "completed",
                    "conclusion": "skipped",
                }
            )
        self.assertEqual(
            self.plan(job_list=current), {"action": "review", "job_id": 20}
        )

    def test_missing_or_cancelled_test_evidence_does_not_resume_repair(self):
        for mutate in (
            lambda j: j.pop(0),
            lambda j: j[1].update(conclusion="cancelled"),
            lambda j: j[1].update(status="in_progress"),
        ):
            current = waiting_jobs()
            mutate(current)
            self.assertEqual(self.plan(job_list=current), {"action": "none"})

    def test_pending_stale_or_protocol_error_never_resumes(self):
        for change in (
            {"reviews_complete": False},
            {"sha": "b" * 40},
            {"state": "pending"},
            {"reason": "protocol", "state": "blocked"},
        ):
            self.assertEqual(
                self.plan(proof={**evidence(), **change}), {"action": "none"}
            )

    def test_running_cancelled_success_and_approval_required_runs_untouched(self):
        for change in (
            {"status": "in_progress"},
            {"status": "queued"},
            {"conclusion": "cancelled"},
            {"conclusion": "success"},
            {"conclusion": "action_required"},
            {"head_sha": "b" * 40},
        ):
            self.assertEqual(self.plan(source={**run(), **change}), {"action": "none"})

    def test_missing_duplicate_failed_or_running_prerequisites_do_not_resume(self):
        for mutate in (
            lambda j: j[0].update(conclusion="failure"),
            lambda j: j.pop(0),
            lambda j: j.append(dict(j[0])),
            lambda j: j[0].update(status="in_progress"),
        ):
            current = jobs()
            mutate(current)
            self.assertEqual(self.plan(job_list=current), {"action": "none"})

    def test_review_permission_or_validation_failure_is_not_retried(self):
        for step in (
            "Review",
            "Validate review execution",
            "Fix",
            "Validate fix execution",
        ):
            current = waiting_jobs()
            current[-2]["steps"].append({"name": step, "conclusion": "failure"})
            self.assertEqual(self.plan(job_list=current), {"action": "none"})

    def test_unrelated_merge_failure_and_findings_seen_by_fix_are_not_retried(self):
        self.assertEqual(self.plan(proof=evidence("blocked")), {"action": "none"})
        current = jobs()
        current[-1]["steps"].append(
            {"name": "Verify live PR eligibility", "conclusion": "failure"}
        )
        self.assertEqual(self.plan(job_list=current), {"action": "none"})

    def test_invalid_job_identity_does_not_produce_rerun(self):
        for value in (True, 0, -1, "21", None):
            current = jobs()
            current[-1]["id"] = value
            self.assertEqual(self.plan(job_list=current), {"action": "none"})

    def test_unknown_failed_job_and_duplicate_identity_are_not_ignored(self):
        current = jobs()
        current.append(
            {
                "id": 30,
                "name": "additional check",
                "status": "completed",
                "conclusion": "failure",
            }
        )  # Opaque fixture job ID.
        self.assertEqual(self.plan(job_list=current), {"action": "none"})
        current = jobs()
        current[-1]["id"] = current[-2]["id"]
        self.assertEqual(self.plan(job_list=current), {"action": "none"})

    def test_malformed_server_shapes_fail_closed(self):
        for source, job_list, proof in (
            ([], jobs(), evidence()),
            (run(), {}, evidence()),
            (run(), [None], evidence()),
            (run(), jobs(), []),
        ):
            self.assertEqual(
                self.policy.resumption_plan(source, job_list, proof, SHA),
                {"action": "none"},
            )


if __name__ == "__main__":
    unittest.main()
