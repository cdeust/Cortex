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


# ── write_time_hint dead-ref states (issue #345) ────────────────────────────
#
# Reproduced live on memory 4341427 (2026-08-08): 3 real repo-relative paths
# graded dead because `directory` was never passed to `remember`, so
# resolution silently fell back to the process's cwd (the repo's PARENT,
# not the repo itself). The naive "no ref found" -> "name the dead refs"
# fix alone still misdiagnoses that case as "these paths are wrong" when
# they are not -- the ROOT they were checked against is. Three mutually
# exclusive states, per `_unverifiable_hint`'s contract:
#   1. no references extracted at all (existing coverage above)
#   2a. references extracted, resolution root is not a real directory
#   2b. references extracted, root is real but was never explicitly given
#   3.  references extracted, root explicit and real, refs genuinely absent


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
