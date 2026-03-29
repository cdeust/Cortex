"""Tests for mcp_server.core.global_detector — auto-classification of global memories."""

from mcp_server.core.global_detector import detect_global, GLOBAL_THRESHOLD


class TestDetectGlobal:
    """Core detection logic."""

    def test_empty_content(self):
        is_g, score, reason = detect_global("")
        assert is_g is False
        assert reason == "empty"

    def test_tool_log_rejected(self):
        is_g, score, reason = detect_global(
            "# Tool: Bash\n**Command:** `ls -la`\n**Output:** stuff"
        )
        assert is_g is False
        assert reason == "tool_log"

    def test_plain_content_not_global(self):
        is_g, score, reason = detect_global("Fixed the button color on the homepage")
        assert is_g is False
        assert reason == "not_global"

    # ── Architecture rules ──────────────────────────────────────────────

    def test_clean_architecture_global(self):
        is_g, score, reason = detect_global(
            "Always follow clean architecture: inner layers never import outer layers. "
            "Use dependency injection for all I/O boundaries."
        )
        assert is_g is True
        assert "architecture" in reason

    def test_solid_principles_global(self):
        is_g, score, reason = detect_global(
            "SOLID principles: single responsibility per class, "
            "dependency inversion for infrastructure."
        )
        assert is_g is True
        assert "architecture" in reason

    def test_design_pattern_alone_not_enough(self):
        """Single weak keyword shouldn't trigger global."""
        is_g, score, reason = detect_global("We used a design pattern here")
        assert is_g is False

    # ── Conventions ─────────────────────────────────────────────────────

    def test_coding_standard_global(self):
        is_g, score, reason = detect_global(
            "Coding standard: always use UTC timestamps in the database layer. "
            "Never use naive datetimes."
        )
        assert is_g is True
        assert "convention" in reason

    def test_team_agreement_global(self):
        is_g, score, reason = detect_global(
            "Team agreement: we always write tests before merging. "
            "Best practice is to keep PRs under 300 lines."
        )
        assert is_g is True
        assert "convention" in reason

    # ── Infrastructure ──────────────────────────────────────────────────

    def test_server_with_ip_global(self):
        is_g, score, reason = detect_global(
            "Production server at 192.168.1.50:5432, PostgreSQL with pgvector. "
            "Daily backups at 3AM UTC."
        )
        assert is_g is True
        assert "infrastructure" in reason

    def test_docker_compose_global(self):
        is_g, score, reason = detect_global(
            "Docker compose for local dev: PostgreSQL on port 5432, "
            "Redis on 6379, CI/CD pipeline runs on GitHub Actions."
        )
        assert is_g is True

    def test_hostname_boost(self):
        is_g, score, reason = detect_global(
            "Server at db.internal with connection string for staging."
        )
        assert is_g is True

    # ── Security ────────────────────────────────────────────────────────

    def test_security_policy_global(self):
        is_g, score, reason = detect_global(
            "API key rotation policy: rotate every 90 days. "
            "Store credentials in the vault, never in source."
        )
        assert is_g is True
        assert "security" in reason

    # ── Cross-project ───────────────────────────────────────────────────

    def test_explicit_cross_project(self):
        is_g, score, reason = detect_global(
            "This applies across all projects: use conventional commits."
        )
        assert is_g is True
        assert "cross_project" in reason

    # ── Tags ────────────────────────────────────────────────────────────

    def test_global_tag_boosts(self):
        is_g, score, reason = detect_global(
            "WAL mode improves concurrent reads",
            tags=["global", "infrastructure"],
        )
        assert is_g is True

    def test_infrastructure_tag_boosts(self):
        is_g, score, reason = detect_global(
            "Connection pool size should be 2x CPU cores",
            tags=["infrastructure"],
        )
        assert is_g is True

    # ── Project-specific anchors ────────────────────────────────────────

    def test_many_file_paths_penalize(self):
        """Content with 3+ file paths is project-specific."""
        is_g, score, reason = detect_global(
            "Clean architecture rule: "
            "src/handlers/remember.py imports src/core/write_gate.py "
            "and src/infrastructure/pg_store.py to compose the pipeline."
        )
        # Penalty should reduce score below threshold
        assert is_g is False or score < GLOBAL_THRESHOLD * 1.5

    def test_single_file_path_mild_penalty(self):
        """One file path only mildly penalizes."""
        is_g, score, reason = detect_global(
            "Clean architecture with dependency injection: "
            "inner layers never import outer layers. "
            "Single responsibility per module. See docs/adr/002.md"
        )
        # Strong enough signals should survive mild penalty
        assert is_g is True

    # ── Threshold boundary ──────────────────────────────────────────────

    def test_score_below_threshold_not_global(self):
        """Weak signal that scores but doesn't clear threshold."""
        is_g, score, reason = detect_global("We used abstraction here")
        assert is_g is False
        assert score > 0
        assert score < GLOBAL_THRESHOLD

    def test_score_returned_accurately(self):
        _, score, _ = detect_global(
            "Clean architecture and dependency injection are our standard approach."
        )
        assert score >= GLOBAL_THRESHOLD
        assert isinstance(score, float)

    # ── Combined signals ────────────────────────────────────────────────

    def test_multi_category_accumulates(self):
        """Signals from multiple categories stack."""
        is_g, score, reason = detect_global(
            "Always use UTC timestamps. Our CI/CD pipeline runs on GitHub Actions. "
            "Follow clean architecture across all projects."
        )
        assert is_g is True
        assert score > GLOBAL_THRESHOLD + 2  # well above threshold
