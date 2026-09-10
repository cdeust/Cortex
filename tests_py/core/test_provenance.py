"""Tests for core/provenance.py — pure grading logic (I6-D6).

Contract:
  - extract_* functions are pure regex extraction, no I/O.
  - grade_provenance() takes pre-resolved per-reference outcomes and
    returns the WORST grade among them (unverifiable < verifiable <
    verified), or unverifiable when there is no extractable reference.
"""

from __future__ import annotations

from mcp_server.core.provenance import (
    UNVERIFIABLE,
    VERIFIABLE,
    VERIFIED,
    ProvenanceReport,
    _build_reason,
    extract_artifact_refs,
    extract_commit_refs,
    extract_url_refs,
    grade_provenance,
    has_citation_ref,
    write_time_hint,
)


# ── Extraction ───────────────────────────────────────────────────────────


class TestExtractCommitRefs:
    def test_extracts_full_sha(self):
        refs = extract_commit_refs("fixed in 8872d565a1b2c3d4e5f60718293a4b5c6d7e8f90")
        assert "8872d565a1b2c3d4e5f60718293a4b5c6d7e8f90" in refs

    def test_extracts_short_sha(self):
        refs = extract_commit_refs("see commit 8872d56 for the fix")
        assert "8872d56" in refs

    def test_excludes_all_digit_tokens(self):
        # A 10-digit run (e.g. a timestamp) is not a plausible commit SHA.
        refs = extract_commit_refs("recorded at 1234567890 in the log")
        assert refs == []

    def test_dedupes(self):
        refs = extract_commit_refs("8872d56 and again 8872d56")
        assert refs.count("8872d56") == 1

    def test_a_skipped_all_digit_token_does_not_abort_the_scan(self):
        # `continue`, not `break`: an ignored token must not truncate the
        # scan, or every SHA after the first counter/timestamp is lost.
        assert extract_commit_refs("1234567890 then 8872d56") == ["8872d56"]

    def test_a_repeated_token_does_not_abort_the_scan(self):
        # Same guard for the dedupe arm of that same `continue`.
        content = "8872d56 again 8872d56 then deadbee"
        assert extract_commit_refs(content) == ["8872d56", "deadbee"]


class TestExtractUrlRefs:
    def test_extracts_url(self):
        refs = extract_url_refs("see https://example.com/docs for details")
        assert refs == ["https://example.com/docs"]

    def test_strips_trailing_punctuation(self):
        refs = extract_url_refs("see (https://example.com/docs).")
        assert refs == ["https://example.com/docs"]

    def test_dedupes(self):
        refs = extract_url_refs("https://a.com and https://a.com again")
        assert refs.count("https://a.com") == 1

    def test_a_trailing_letter_is_not_stripped(self):
        # The cut set is exactly `).,;:'"` — widening it would silently eat
        # the last character of a legitimate path.
        url = "https://example.com/PATHX"
        assert extract_url_refs(f"see {url} for details") == [url]


class TestExtractArtifactRefs:
    def test_extracts_path_and_digest(self):
        content = (
            "**Artifact:** `/home/x/.claude/methodology/artifacts/2026-07/"
            "0123456789abcdef.md` (5000 chars full output)"
        )
        refs = extract_artifact_refs(content)
        assert len(refs) == 1
        path, digest = refs[0]
        assert digest == "0123456789abcdef"
        assert path.endswith("0123456789abcdef.md")

    def test_no_artifact_ref_returns_empty(self):
        assert extract_artifact_refs("plain text, no artifact pointer") == []

    def test_dedupes_a_repeated_path(self):
        path = "artifacts/2026-07/0123456789abcdef.md"
        refs = extract_artifact_refs(f"{path} and again {path}")
        assert refs == [(path, "0123456789abcdef")]


class TestHasCitationRef:
    def test_doi_detected(self):
        assert has_citation_ref("Johnson (1993), doi:10.1037/0033-2909.114.1.3") is True

    def test_arxiv_detected(self):
        assert has_citation_ref("see arXiv:2301.12345 for details") is True

    def test_plain_text_not_detected(self):
        assert has_citation_ref("no citation here at all") is False


# ── Grading combination ───────────────────────────────────────────────────


def _grade(**kwargs) -> ProvenanceReport:
    defaults = dict(
        memory_id=1,
        file_refs=[],
        existing_paths=set(),
        commit_refs=[],
        commit_verdicts={},
        url_refs=[],
        url_verdicts={},
        artifact_refs=[],
        artifact_verdicts={},
        has_citation=False,
    )
    defaults.update(kwargs)
    return grade_provenance(**defaults)


class TestGradeNoRefs:
    def test_no_extractable_reference_is_unverifiable(self):
        report = _grade()
        assert report.grade == UNVERIFIABLE
        assert report.reason == "no_extractable_reference"


class TestGradeFileRefs:
    def test_all_files_exist_is_verified(self):
        report = _grade(file_refs=["a.py"], existing_paths={"a.py"})
        assert report.grade == VERIFIED

    def test_missing_file_is_unverifiable(self):
        report = _grade(file_refs=["a.py"], existing_paths=set())
        assert report.grade == UNVERIFIABLE
        assert "a.py" in report.dead_refs


class TestGradeCommitRefs:
    def test_found_commit_is_verified(self):
        report = _grade(commit_refs=["8872d56"], commit_verdicts={"8872d56": True})
        assert report.grade == VERIFIED

    def test_unresolvable_commit_is_verifiable_not_unverifiable(self):
        # Per I6-D6: a commit ref never grades UNVERIFIABLE by itself — a
        # stale/shallow local clone is indistinguishable from a dead SHA.
        report = _grade(commit_refs=["deadbee"], commit_verdicts={"deadbee": False})
        assert report.grade == VERIFIABLE
        assert "deadbee" in report.uncheckable_refs


class TestGradeUrlRefs:
    def test_reachable_url_is_verifiable_not_verified(self):
        # URLs can never raise a memory to VERIFIED (the web fluctuates).
        report = _grade(
            url_refs=["https://a.com"], url_verdicts={"https://a.com": True}
        )
        assert report.grade == VERIFIABLE

    def test_dead_url_is_unverifiable(self):
        report = _grade(
            url_refs=["https://a.com"], url_verdicts={"https://a.com": False}
        )
        assert report.grade == UNVERIFIABLE
        assert report.dead_refs == ["https://a.com"]

    def test_unsampled_url_is_verifiable_not_penalized(self):
        # verdict=None means "not checked this pass" (bounded sample) —
        # must never be treated as dead.
        report = _grade(
            url_refs=["https://a.com"], url_verdicts={"https://a.com": None}
        )
        assert report.grade == VERIFIABLE
        assert report.uncheckable_refs == ["https://a.com"]


class TestGradeArtifactRefs:
    def test_matching_digest_is_verified(self):
        report = _grade(
            artifact_refs=[("art.md", "abc123")],
            artifact_verdicts={"art.md": True},
        )
        assert report.grade == VERIFIED

    def test_missing_or_mismatched_digest_is_unverifiable(self):
        report = _grade(
            artifact_refs=[("art.md", "abc123")],
            artifact_verdicts={"art.md": False},
        )
        assert report.grade == UNVERIFIABLE
        assert "art.md" in report.dead_refs


class TestGradeCitationRefs:
    def test_citation_alone_is_verifiable_at_best(self):
        report = _grade(has_citation=True)
        assert report.grade == VERIFIABLE

    def test_citation_never_reaches_verified(self):
        # Even with an otherwise-verified file ref, a memory that ALSO
        # carries an uncheckable citation caps at verifiable (worst-case
        # combination — citation contributes a VERIFIABLE outcome).
        report = _grade(file_refs=["a.py"], existing_paths={"a.py"}, has_citation=True)
        assert report.grade == VERIFIABLE


class TestGradeCombination:
    def test_mixed_verified_and_verifiable_yields_verifiable(self):
        report = _grade(
            file_refs=["a.py"],
            existing_paths={"a.py"},
            commit_refs=["deadbee"],
            commit_verdicts={"deadbee": False},
        )
        assert report.grade == VERIFIABLE

    def test_any_dead_ref_dominates_to_unverifiable(self):
        report = _grade(
            file_refs=["a.py", "b.py"],
            existing_paths={"a.py"},  # b.py missing
            commit_refs=["8872d56"],
            commit_verdicts={"8872d56": True},
        )
        assert report.grade == UNVERIFIABLE
        assert "b.py" in report.dead_refs

    def test_all_verified_across_types_is_verified(self):
        report = _grade(
            file_refs=["a.py"],
            existing_paths={"a.py"},
            commit_refs=["8872d56"],
            commit_verdicts={"8872d56": True},
            artifact_refs=[("art.md", "abc123")],
            artifact_verdicts={"art.md": True},
        )
        assert report.grade == VERIFIED

    def test_ref_counts_reported(self):
        report = _grade(
            file_refs=["a.py"],
            existing_paths={"a.py"},
            commit_refs=["8872d56"],
            commit_verdicts={"8872d56": True},
            has_citation=True,
        )
        assert report.ref_counts == {
            "file": 1,
            "commit": 1,
            "url": 0,
            "artifact": 0,
            "citation": 1,
        }


# ── Missing verdict entries ──────────────────────────────────────────────


class TestGradeMissingVerdictEntries:
    """The documented precondition: a ref absent from its verdicts dict
    takes the LEAST-favorable outcome for its type, never the favorable
    one. A verdict dict truncated by a bounded sample must never silently
    promote a memory (issue #389)."""

    def test_commit_absent_from_verdicts_is_uncheckable_not_verified(self):
        report = _grade(commit_refs=["8872d56"], commit_verdicts={})
        assert report.grade == VERIFIABLE
        assert report.uncheckable_refs == ["8872d56"]

    def test_artifact_absent_from_verdicts_is_dead_not_verified(self):
        report = _grade(artifact_refs=[("art.md", "abc123")], artifact_verdicts={})
        assert report.grade == UNVERIFIABLE
        assert report.dead_refs == ["art.md"]


# ── Reported fields ──────────────────────────────────────────────────────


class TestGradeReportFields:
    """Every field the caller reads back, on both return paths (issue #389).

    The grade itself is covered above; these pin the identity, counts and
    reason that travel with it.
    """

    def test_empty_report_carries_id_zeroed_counts_and_empty_lists(self):
        report = _grade(memory_id=7)
        assert report.memory_id == 7
        assert report.ref_counts == {
            "file": 0,
            "commit": 0,
            "url": 0,
            "artifact": 0,
            "citation": 0,
        }
        assert report.dead_refs == []
        assert report.uncheckable_refs == []

    def test_graded_report_carries_id_and_all_verified_reason(self):
        report = _grade(memory_id=7, file_refs=["a.py"], existing_paths={"a.py"})
        assert report.memory_id == 7
        assert report.reason == "all_refs_verified"

    def test_dead_file_ref_is_named_in_the_reason(self):
        report = _grade(file_refs=["a.py"], existing_paths=set())
        assert report.reason == "dead_refs: a.py"

    def test_uncheckable_commit_is_named_in_the_reason(self):
        report = _grade(commit_refs=["deadbee"], commit_verdicts={"deadbee": False})
        assert report.reason == "uncheckable_refs: deadbee"

    def test_citation_count_is_zero_when_no_citation_is_present(self):
        report = _grade(file_refs=["a.py"], existing_paths={"a.py"})
        assert report.ref_counts["citation"] == 0


# ── Reason wording ───────────────────────────────────────────────────────


class TestBuildReason:
    """`_build_reason` maps (grade, dead, uncheckable) to the stored reason.

    One of its four branches is unreachable through `grade_provenance`:
    every path that appends an UNVERIFIABLE outcome also appends to `dead`,
    so `grade == UNVERIFIABLE and not dead` never reaches this helper, and
    the empty-outcome path hardcodes the same string rather than calling it.
    The other three are reachable and are also pinned end-to-end by
    `TestGradeReportFields`; they are asserted here as well because these
    unit-level cases carry the boundary inputs (the three-ref join cap in
    particular) the end-to-end tests do not supply (issue #389).
    """

    def test_unverifiable_with_dead_refs_names_them(self):
        assert _build_reason(UNVERIFIABLE, ["a.py"], []) == "dead_refs: a.py"

    def test_dead_refs_are_comma_joined_and_capped_at_three(self):
        reason = _build_reason(UNVERIFIABLE, ["a.py", "b.py", "c.py", "d.py"], [])
        assert reason == "dead_refs: a.py, b.py, c.py"

    def test_unverifiable_without_dead_refs_reports_no_reference(self):
        assert _build_reason(UNVERIFIABLE, [], []) == "no_extractable_reference"

    def test_dead_refs_alone_do_not_explain_a_passing_grade(self):
        # `and`, not `or`: dead refs only ever explain an UNVERIFIABLE grade.
        assert _build_reason(VERIFIED, ["a.py"], []) == "all_refs_verified"

    def test_verifiable_with_uncheckable_refs_names_them(self):
        reason = _build_reason(VERIFIABLE, [], ["deadbee"])
        assert reason == "uncheckable_refs: deadbee"

    def test_uncheckable_refs_are_comma_joined_and_capped_at_three(self):
        reason = _build_reason(VERIFIABLE, [], ["a", "b", "c", "d"])
        assert reason == "uncheckable_refs: a, b, c"

    def test_uncheckable_refs_alone_do_not_explain_a_verified_grade(self):
        assert _build_reason(VERIFIED, [], ["deadbee"]) == "all_refs_verified"


# ── write_time_hint (M-D5, 7.5) ─────────────────────────────────────────────


def _report(grade: str) -> ProvenanceReport:
    return ProvenanceReport(memory_id=0, grade=grade, ref_counts={})


class TestWriteTimeHint:
    def test_verified_hint(self):
        assert "verified locally" in write_time_hint(_report(VERIFIED))

    def test_verifiable_hint(self):
        hint = write_time_hint(_report(VERIFIABLE))
        assert "not conclusively checked" in hint

    def test_unverifiable_hint_non_deliberate_is_plain(self):
        hint = write_time_hint(_report(UNVERIFIABLE), write_class="auto")
        assert "No checkable reference" in hint
        assert "durable claim" not in hint

    def test_unverifiable_hint_deliberate_gets_call_to_action(self):
        hint = write_time_hint(_report(UNVERIFIABLE), write_class="deliberate")
        assert "No checkable reference" in hint
        assert "durable claim" in hint

    def test_unverifiable_hint_no_write_class_is_plain(self):
        hint = write_time_hint(_report(UNVERIFIABLE))
        assert "durable claim" not in hint

    def test_hint_never_persisted_is_a_pure_function(self):
        # Same report + write_class always yields the same string -- no
        # hidden state, no I/O (contract: deterministic lookup only).
        r = _report(UNVERIFIABLE)
        assert write_time_hint(r, "deliberate") == write_time_hint(r, "deliberate")


# source: ADR-0923


def _dead_report(
    dead_refs: list[str], *, file_count: int | None = None
) -> ProvenanceReport:
    n = file_count if file_count is not None else len(dead_refs)
    return ProvenanceReport(
        memory_id=0,
        grade=UNVERIFIABLE,
        ref_counts={"file": n, "commit": 0, "url": 0, "artifact": 0, "citation": 0},
        dead_refs=list(dead_refs),
        reason=f"dead_refs: {', '.join(dead_refs[:3])}",
    )


class TestWriteTimeHintDeadRefStates:
    def test_state1_no_refs_at_all_keeps_plain_wording(self):
        """State 1: zero extractable references — unchanged since before
        #345 (nothing to name, no root to blame)."""
        hint = write_time_hint(_report(UNVERIFIABLE))
        assert "No checkable reference found" in hint

    def test_state2a_root_missing_on_disk_names_root_not_paths(self):
        """State 2a: the resolution root itself does not exist — the hint
        must blame the ROOT, not imply the paths are individually wrong."""
        report = _dead_report(["src/a.py"])
        hint = write_time_hint(
            report,
            resolution_root="/no/such/directory",
            resolution_root_explicit=True,
            resolution_root_exists=False,
        )
        assert "/no/such/directory" in hint
        assert "not a directory on disk" in hint
        assert "src/a.py" in hint

    def test_state2b_implicit_root_names_root_and_says_no_directory_passed(self):
        """State 2b (the live repro): references are real, but `directory`
        was never passed, so resolution used the implicit cwd — the hint
        must name that root AND tell the writer to pass `directory`."""
        report = _dead_report(
            ["mcp_server/core/decay_cycle.py", "tests_py/core/test_decay_cycle.py"]
        )
        hint = write_time_hint(
            report,
            resolution_root="/Users/cdeust/Developments",
            resolution_root_explicit=False,
            resolution_root_exists=True,
        )
        assert "/Users/cdeust/Developments" in hint
        assert "no `directory` was passed" in hint
        assert "mcp_server/core/decay_cycle.py" in hint
        assert "not a directory on disk" not in hint

    def test_state3_explicit_root_names_root_and_dead_refs_only(self):
        """State 3: a real, explicitly-given root — the classic dead-ref
        case from the filed issue (#345 original repro)."""
        report = _dead_report(["plugins/hypermnesia-mcp-codex/.mcp.json"])
        hint = write_time_hint(
            report,
            resolution_root="/repo/Cortex",
            resolution_root_explicit=True,
            resolution_root_exists=True,
        )
        assert "/repo/Cortex" in hint
        assert "plugins/hypermnesia-mcp-codex/.mcp.json" in hint
        assert "no `directory` was passed" not in hint
        assert "No checkable reference found" not in hint

    def test_dead_ref_hint_never_claims_none_found(self):
        """The exact defect from the issue: `checkable_refs` non-zero and
        the hint claiming none was found must never co-occur."""
        report = _dead_report(["a.py", "b.py", "c.py"])
        hint = write_time_hint(
            report,
            resolution_root="/repo",
            resolution_root_explicit=True,
            resolution_root_exists=True,
        )
        assert "No checkable reference found" not in hint

    def test_more_than_three_dead_refs_are_capped_with_a_count(self):
        report = _dead_report(["a.py", "b.py", "c.py", "d.py", "e.py"])
        hint = write_time_hint(
            report,
            resolution_root="/repo",
            resolution_root_explicit=True,
            resolution_root_exists=True,
        )
        assert "a.py" in hint and "b.py" in hint and "c.py" in hint
        assert "d.py" not in hint
        assert "+2 more" in hint

    def test_deliberate_suffix_still_appended_on_dead_ref_hint(self):
        report = _dead_report(["a.py"])
        hint = write_time_hint(
            report,
            "deliberate",
            resolution_root="/repo",
            resolution_root_explicit=True,
            resolution_root_exists=True,
        )
        assert "durable claim" in hint

    def test_default_params_preserve_pre_345_explicit_real_root_behavior(self):
        """Callers that have not been updated to pass the new keyword-only
        params (default explicit=True, exists=True) get state-3 wording,
        not a false "root missing" or "root implicit" claim."""
        report = _dead_report(["a.py"])
        hint = write_time_hint(report)
        assert "not a directory on disk" not in hint
        assert "no `directory` was passed" not in hint
        assert "a.py" in hint

    # ── Exact-text pins (mutation-kill coverage, issue #345) ────────────────
    #
    # The tests above assert substrings/absences; mutmut's string-literal and
    # boundary mutants on these three state functions survive substring-only
    # coverage (e.g. a case-flip or an "XX"-marker mutation on a sentence
    # never individually asserted). These pin the FULL rendered string for
    # one representative case per state, and the numeric/separator/boundary
    # edges that substring checks cannot see.

    def test_state2a_full_text_exact(self):
        report = _dead_report(["src/a.py"])
        hint = write_time_hint(
            report,
            resolution_root="/tmp/nope",
            resolution_root_explicit=True,
            resolution_root_exists=False,
        )
        assert hint == (
            "1 checkable reference(s) could not be resolved because the "
            "resolution root '/tmp/nope' is not a directory on disk: "
            "src/a.py. Pass a valid `directory`, then supersede this memory."
        )

    def test_state2b_full_text_exact(self):
        report = _dead_report(["src/a.py"])
        hint = write_time_hint(
            report,
            resolution_root="/tmp/parent",
            resolution_root_explicit=False,
            resolution_root_exists=True,
        )
        assert hint == (
            "1 of 1 checkable reference(s) could not be resolved against "
            "'/tmp/parent' -- no `directory` was passed to this write, so "
            "resolution defaulted to the process's current working "
            "directory: src/a.py. Pass `directory` explicitly (your "
            "project root) and retry, or drop the reference if it is "
            "genuinely gone."
        )

    def test_state3_full_text_exact(self):
        report = _dead_report(["src/a.py"])
        hint = write_time_hint(
            report,
            resolution_root="/repo",
            resolution_root_explicit=True,
            resolution_root_exists=True,
        )
        assert hint == (
            "1 of 1 checkable reference(s) could not be resolved against "
            "'/repo': src/a.py. Fix the path/URL or drop it, then "
            "supersede this memory."
        )

    def test_named_dead_refs_uses_comma_space_separator(self):
        report = _dead_report(["a.py", "b.py"])
        hint = write_time_hint(
            report,
            resolution_root="/repo",
            resolution_root_explicit=True,
            resolution_root_exists=True,
        )
        assert "a.py, b.py" in hint

    def test_exactly_three_dead_refs_no_more_suffix(self):
        # remaining == 0: must NOT show a "(+0 more)" tail.
        report = _dead_report(["a.py", "b.py", "c.py"])
        hint = write_time_hint(
            report,
            resolution_root="/repo",
            resolution_root_explicit=True,
            resolution_root_exists=True,
        )
        assert "(+" not in hint

    def test_exactly_four_dead_refs_shows_plus_one_more(self):
        # remaining == 1: the `> 0` boundary, distinct from the `> 1` and
        # `>= 0` off-by-one mutants.
        report = _dead_report(["a.py", "b.py", "c.py", "d.py"])
        hint = write_time_hint(
            report,
            resolution_root="/repo",
            resolution_root_explicit=True,
            resolution_root_exists=True,
        )
        assert "(+1 more)" in hint

    def test_default_resolution_root_falls_back_to_unresolved_marker(self):
        """No `resolution_root` passed at all (default "") with dead refs
        present -- the `resolution_root or "(unresolved)"` fallback must
        fire, both proving the default is empty (not a non-empty marker)
        and pinning the literal fallback text EXACTLY (not merely as a
        substring -- a mutated marker like "XX(unresolved)XX" would also
        satisfy a substring check)."""
        report = _dead_report(["a.py"])
        hint = write_time_hint(report)
        assert hint == (
            "1 of 1 checkable reference(s) could not be resolved against "
            "'(unresolved)': a.py. Fix the path/URL or drop it, then "
            "supersede this memory."
        )
