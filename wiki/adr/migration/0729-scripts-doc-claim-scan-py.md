# ADR-0729: scripts/doc_claim_scan.py implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `scripts/doc_claim_scan.py`; original SHA-256 `9e61b18cb7b29908792072d6f902a48873cb9b43e1ba88d43ad2212c966cd1c3`.

## Original docstring, lines 1–13

````text
"""Claim-scanning machinery for scripts/check_doc_claims.py.

Extracted (issue #293, Extract Function/Move Function) to keep
check_doc_claims.py under the repo's 300-line file cap. Answers "does a
scanned file's prose claim (a count, phrased as 'N things') agree with a
canonical number" and "which lines have declared they are not a claim."

`scanned_files`/`read_fn` are explicit parameters rather than module
globals, so check_doc_claims.py's thin wrappers (which do reference its own
`SCANNED_FILES`/`read` bare names, and so DO see `gate.read = fake` /
`gate.SCANNED_FILES = (...)` patches in tests_py/scripts/test_check_doc_claims.py)
can forward them through unchanged.
"""
````

## Original comment, lines 25–30

````text
# A line whose number counts something else declares which family it is not a
# claim for. Rewording the prose to dodge a pattern would hide a true, measured
# number to keep the gate quiet; declaring it keeps the number and puts the
# exemption on the record, at the one site that knows why it is not a claim.
# The label must match a claim family exactly — an unrecognised or misspelled
# label exempts nothing, so the marker fails closed.
````

## Original docstring, lines 82–87

````text
"""Report claims that disagree — and the absence of any claim at all.

    A pattern that matches nothing would pass silently forever, which is how a
    gate becomes decorative: the vacuity guard makes a reworded (or deleted)
    claim a build failure rather than an unnoticed loss of coverage.
    """
````

