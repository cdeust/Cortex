# Local merge repair and bounded helper lifecycle

Base: PR #816 head 782c5918ea76beafda836c1d18fa9bde8e944697.
Source review: https://github.com/cdeust/Cortex/pull/816#issuecomment-6460532248
Scope: local helper, dispatcher/installer interval wiring, tests and docs.
Shared native reconciliation policy and all installed services remain untouched.

## Merge infrastructure repair

The actual check-to-tick reproducer returned wait for a failed merge eligibility
step despite complete clean native proof, green prerequisites and a successful
review job. The merge-side partner now enters repair only for that eligible
non-readiness failure. It reuses policy.MERGE and preserves run/attempt/head/proof
rereads. Exact native readiness failures still wait for GitHub's sole rerun path.
Current holds and a head change after both run reads prevent any local model.
Tests assert the successful repair path as a positive control and zero POSTs.

## Configured process budget

Read-only service inspection found StartInterval=60 and no dispatcher interval
argument. The installer now passes the exact requested interval to both launchd
and the dispatcher. The optional dispatcher flag defaults to the existing
60-second operational value and validates positive integers, preserving legacy
inspection commands. No new algorithmic delay or installed-service change was
introduced.

The baseline Python 3.14.4 probe used run(timeout=0.2): it returned in 0.205 seconds
but its descendant survived the leader timeout. The probe explicitly killed
only its private group and verified the descendant absent. Thus the evidence
here is a leaked descendant, not a reproduced communicate hang on this host.

The helper now starts a private POSIX session. On timeout it kills only that
owned group, closes inherited pipe readers and waits for its leader with a
separate bounded cleanup budget. Nominal timeout and cleanup are each bounded
by the configured interval; this does not promise one interval total under
exceptional cleanup. Programming exceptions are re-raised after cleanup.

The final real probe used a one-second fixture budget and returned in 1.006
seconds with environment/helper_failure and timeout_seconds=1. The descendant
was absent, the caller group was preserved and another independently created
session remained live until explicitly stopped by the probe. Timeout queue
tests preserve accepted settlement and process later authorized work. Waiting
and failure paths issue neither a POST nor a model call.

## Verification boundaries

Actual project pytest configuration is prepend with empty addopts; ci.json has
no import-mode flag. The earlier explicit importlib run is an additional stress
probe, not the CI default. Both modes and the standard-library CI suites are
checked for this patch. --noconftest keeps these bounded script checks away from
the production database; full application acceptance remains hosted CI.

Final bounded CI-script checks: configured pytest prepend passed 323 tests and
399 subtests in 10.73 seconds; the additional importlib probe passed the same
323 tests and 399 subtests in 11.16 seconds. Standard-library discovery passed
323 tests in 11.70 seconds. Ruff check/format and the actual Cortex 300/40
craftsmanship scanner passed without a waiver. The focused autopilot suite
passed 85 tests and 51 subtests.
No model, Cargo build, user terminal or installed launchd service was started,
changed or stopped by this patch. All process signals targeted probe-owned groups.
