# ADR-0710: scripts/check_ci_gate_complete.py implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `scripts/check_ci_gate_complete.py`; original SHA-256 `c24b9eb7c5ed74d5ce736323579042ea009905eb049c93028c0311c06b9eb579`.

## Original docstring, lines 1–10

````text
"""Static CI-gate coverage and prerequisite checks without YAML dependencies.

Every job must be a direct CI Green dependency or declare a conditional
post-merge exemption. Every conditional gated job belongs to ALLOWED_SKIPS;
the runtime checker independently verifies the reason for each actual skip.
CI Green must always run to report failures and rejected skips.

Source: tasks/codex-green-remediation-plan.md W1-2 and GitHub workflow syntax:
https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#jobsjob_idneeds
"""
````

## Original comment, lines 26–27

````text
# The aggregate context for this workflow. Renaming it requires updating
# branch protection, hence a named constant rather than a literal.
````

