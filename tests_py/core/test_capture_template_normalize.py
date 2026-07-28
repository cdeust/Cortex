"""Tests for mcp_server.core.capture_template_normalize (M-D1, INC 7.3).

Covers: auto-capture template variants (light-value Read/Glob/Grep,
high-value Bash/Edit stdout, gisted-with-artifact), the derived-fact
template (memify_derive), idempotence, and the safety gate that leaves
deliberate/free-form content untouched.
"""

from mcp_server.core.capture_template_normalize import (
    capture_template_normalize,
    is_auto_capture_template,
    is_derived_fact_template,
)


class TestIsAutoCaptureTemplate:
    def test_detects_tool_header(self):
        assert is_auto_capture_template("# Tool: Read\n**Read:** `/a/b.py`")

    def test_rejects_deliberate_note(self):
        assert not is_auto_capture_template(
            "Decided to use pgvector HNSW for ANN — 3x faster than IVFFlat."
        )

    def test_rejects_empty(self):
        assert not is_auto_capture_template("")

    def test_rejects_markdown_heading_that_is_not_the_marker(self):
        # A deliberate note that happens to start with a level-1 heading
        # but isn't the "# Tool: X" marker must not be treated as a capture.
        assert not is_auto_capture_template("# Design notes\nSome content.")


class TestIsDerivedFactTemplate:
    def test_detects_linked_sentence(self):
        content = (
            "PaymentGateway and StripeAdapter are strongly linked "
            "(depends_on, weight=12.5)"
        )
        assert is_derived_fact_template(content)

    def test_rejects_free_prose_mentioning_linked(self):
        assert not is_derived_fact_template(
            "The two modules are strongly linked but I haven't measured the weight."
        )


class TestNormalizeAutoCaptureLightValue:
    def test_read_capture_strips_header_and_label_keeps_path(self):
        raw = "# Tool: Read\n**Read:** `/Users/x/memories/checkpoints/uuid-1.md`"
        out = capture_template_normalize(raw)
        assert "# Tool:" not in out
        assert "**Read:**" not in out
        assert "/Users/x/memories/checkpoints/uuid-1.md" in out

    def test_two_different_checkpoint_reads_remain_distinguishable(self):
        a = capture_template_normalize(
            "# Tool: Read\n**Read:** `/Users/x/memories/checkpoints/uuid-AAAA.md`"
        )
        b = capture_template_normalize(
            "# Tool: Read\n**Read:** `/Users/x/memories/checkpoints/uuid-BBBB.md`"
        )
        assert a != b

    def test_glob_capture(self):
        raw = "# Tool: Glob\n**Glob:** `*.py` (root=`/repo`)"
        out = capture_template_normalize(raw)
        assert "# Tool:" not in out
        assert "**Glob:**" not in out
        assert "*.py" in out and "/repo" in out

    def test_grep_capture(self):
        raw = "# Tool: Grep\n**Grep:** `TODO` in `/repo/src`"
        out = capture_template_normalize(raw)
        assert "**Grep:**" not in out
        assert "TODO" in out


class TestNormalizeAutoCaptureHighValue:
    def test_bash_stdout_capture(self):
        raw = (
            "# Tool: Bash\n"
            "**Command:** `pytest -q`\n"
            "\n## Output\n\n"
            "**stdout:**\n```\n12 passed in 3.2s\n```"
        )
        out = capture_template_normalize(raw)
        assert "# Tool:" not in out
        assert "## Output" not in out
        assert "**Command:**" not in out
        assert "pytest -q" in out
        assert "12 passed in 3.2s" in out

    def test_edit_before_after_capture(self):
        raw = (
            "# Tool: Edit\n"
            "**File:** `/repo/src/x.py`\n"
            "\n## Output\n\n"
            "**before:**\n```\nold_line\n```\n\n**after:**\n```\nnew_line\n```"
        )
        out = capture_template_normalize(raw)
        assert "# Tool:" not in out
        assert "/repo/src/x.py" in out
        assert "old_line" in out and "new_line" in out

    def test_raw_output_fence_wrapped(self):
        raw = "# Tool: Bash\n**Command:** `ls`\n\n**Output:**\n```\nfile1\nfile2\n```"
        out = capture_template_normalize(raw)
        assert "**Output:**" not in out
        assert "```" not in out
        assert "file1" in out and "file2" in out

    def test_artifact_pointer_line_dropped(self):
        raw = (
            "# Tool: Bash\n**Command:** `big-command`\n\n"
            "## Output\n\ngist text\n\n"
            "**Artifact:** `/store/ab12cd.txt` (50000 chars full output)"
        )
        out = capture_template_normalize(raw)
        assert "**Artifact:**" not in out
        assert "ab12cd.txt" not in out
        assert "gist text" in out


class TestNormalizeDerivedFact:
    def test_strips_connective_keeps_entities_and_weight(self):
        raw = (
            "PaymentGateway and StripeAdapter are strongly linked "
            "(depends_on, weight=12.5)"
        )
        out = capture_template_normalize(raw)
        assert "are strongly linked" not in out
        assert "PaymentGateway" in out
        assert "StripeAdapter" in out
        assert "depends_on" in out
        assert "12.5" in out

    def test_two_different_entity_pairs_remain_distinguishable(self):
        a = capture_template_normalize(
            "Foo and Bar are strongly linked (depends_on, weight=10.0)"
        )
        b = capture_template_normalize(
            "Baz and Qux are strongly linked (depends_on, weight=10.0)"
        )
        assert a != b


class TestSafetyGate:
    def test_deliberate_note_untouched(self):
        content = "Decided to use pgvector HNSW (m=16, ef_construction=64) for ANN."
        assert capture_template_normalize(content) == content

    def test_free_form_note_with_hash_heading_untouched(self):
        content = "# Meeting notes\nDiscussed the roadmap for Q3."
        assert capture_template_normalize(content) == content

    def test_empty_string_untouched(self):
        assert capture_template_normalize("") == ""

    def test_never_returns_empty_falls_back_to_original(self):
        # Only a bare header line, no payload at all.
        raw = "# Tool: Bash"
        out = capture_template_normalize(raw)
        assert out  # never empty
        assert out == raw  # skeleton-only input has no payload to keep


class TestIdempotence:
    def test_auto_capture_idempotent(self):
        raw = (
            "# Tool: Bash\n**Command:** `pytest -q`\n\n"
            "## Output\n\n**stdout:**\n```\n12 passed\n```"
        )
        once = capture_template_normalize(raw)
        twice = capture_template_normalize(once)
        assert once == twice

    def test_derived_fact_idempotent(self):
        raw = "Foo and Bar are strongly linked (depends_on, weight=10.0)"
        once = capture_template_normalize(raw)
        twice = capture_template_normalize(once)
        assert once == twice

    def test_light_value_capture_idempotent(self):
        raw = "# Tool: Read\n**Read:** `/a/b.py`"
        once = capture_template_normalize(raw)
        twice = capture_template_normalize(once)
        assert once == twice

    def test_deliberate_note_idempotent(self):
        raw = "Decided to use pgvector HNSW for ANN."
        assert capture_template_normalize(raw) == capture_template_normalize(
            capture_template_normalize(raw)
        )
