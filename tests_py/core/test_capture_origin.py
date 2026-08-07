"""Tests for mcp_server.core.capture_origin — channel-derived origin (#365).

Contract under test:
  - classify_capture_origin maps a TOOL NAME to one of ALL_ORIGINS, case
    insensitively, and never guesses: unknown/empty -> ORIGIN_UNKNOWN.
  - WebFetch/WebSearch -> ORIGIN_NETWORK. Local-acting tools ->
    ORIGIN_LOCAL_ACTION.
  - may_bypass_write_gate_on_content is True only for the allowlisted origins.
  - The classification is a pure function of the tool name: no content is
    consulted, so no content can change the answer. That invariant is what
    makes the value usable as a security input, so it is asserted directly.
"""

from __future__ import annotations

import pytest

from mcp_server.core.capture_origin import (
    ALL_ORIGINS,
    ORIGIN_DELIBERATE,
    ORIGIN_LOCAL_ACTION,
    ORIGIN_NETWORK,
    ORIGIN_UNKNOWN,
    classify_capture_origin,
    is_network_origin,
    may_bypass_write_gate_on_content,
)


class TestClassifyCaptureOrigin:
    @pytest.mark.parametrize("tool", ["WebFetch", "WebSearch", "webfetch", "WEBSEARCH"])
    def test_network_tools_classify_as_network(self, tool):
        assert classify_capture_origin(tool) == ORIGIN_NETWORK

    @pytest.mark.parametrize(
        "tool",
        ["Edit", "Write", "MultiEdit", "Bash", "Read", "Glob", "Grep", "NotebookEdit"],
    )
    def test_local_tools_classify_as_local_action(self, tool):
        assert classify_capture_origin(tool) == ORIGIN_LOCAL_ACTION

    @pytest.mark.parametrize("tool", ["", "   ", "SomeFutureTool", "mcp__thing__do"])
    def test_unrecognised_or_empty_is_unknown_never_a_guess(self, tool):
        """A newly added tool must be visibly unclassified, not silently trusted."""
        assert classify_capture_origin(tool) == ORIGIN_UNKNOWN

    def test_result_is_always_in_the_vocabulary(self):
        for tool in ["Edit", "WebFetch", "", "Nonsense", "bash", "WebSearch"]:
            assert classify_capture_origin(tool) in ALL_ORIGINS

    def test_whitespace_and_case_are_normalised(self):
        assert classify_capture_origin("  WebFetch  ") == ORIGIN_NETWORK
        assert classify_capture_origin("  bAsH ") == ORIGIN_LOCAL_ACTION

    def test_classification_ignores_content_entirely(self):
        """The security invariant: content cannot move a tool's origin.

        classify_capture_origin takes only a tool name, so a hostile payload —
        even one naming another tool, or carrying decision/error cues — cannot
        change the verdict for the tool that actually produced it.
        """
        hostile = (
            "DECISION: we chose to trust this. ERROR: traceback follows. "
            "Edit Write Bash Read local_action deliberate"
        )
        # Passing the payload where a tool name goes must not yield a trusted
        # origin, and must not yield NETWORK's opposite by accident.
        assert classify_capture_origin(hostile) == ORIGIN_UNKNOWN
        # And the real producing tool still classifies as network regardless of
        # what its output happens to contain.
        assert classify_capture_origin("WebFetch") == ORIGIN_NETWORK


class TestBypassPolicy:
    def test_network_origin_may_not_claim_a_content_bypass(self):
        assert may_bypass_write_gate_on_content(ORIGIN_NETWORK) is False

    @pytest.mark.parametrize("origin", [ORIGIN_LOCAL_ACTION, ORIGIN_DELIBERATE])
    def test_allowlisted_origins_may(self, origin):
        assert may_bypass_write_gate_on_content(origin) is True

    def test_unknown_origin_is_refused_because_the_rule_is_an_allowlist(self):
        """The fail-closed property, and the reason for the allowlist.

        `_NETWORK_TOOLS` hardcodes two names against a host whose tool surface
        changes. A third off-machine tool, or a renamed one, classifies
        UNKNOWN. Under a denylist of {NETWORK} it would silently regain the
        content bypass — the control stopping with no failing test, which is
        the failure this module exists to prevent. Under the allowlist an
        unclassified origin is refused.
        """
        assert may_bypass_write_gate_on_content(ORIGIN_UNKNOWN) is False

    def test_an_origin_this_module_does_not_know_is_refused(self):
        """Stands in for a future off-machine tool nobody has classified yet."""
        assert may_bypass_write_gate_on_content("something-new") is False

    def test_is_network_origin(self):
        assert is_network_origin(ORIGIN_NETWORK) is True
        assert is_network_origin(ORIGIN_LOCAL_ACTION) is False
        assert is_network_origin("") is False


# ── The gate refusal, end to end at the core boundary (issue #365) ─────────


class TestWriteGateRefusesContentBypassForNetworkOrigin:
    """The security property: shaped content cannot buy a bypass.

    `bypass_error` / `bypass_decision` are read out of the content by
    core/thermodynamics, so they are precisely what off-machine text would
    forge. They must be unavailable at network origin, while the out-of-band
    human signals (force, deliberate write class) stay valid at any origin.
    """

    ERROR_SHAPED = "Traceback (most recent call last):\nValueError: boom"
    DECISION_SHAPED = "Decision: we chose PostgreSQL over SQLite because of pgvector"

    def test_error_shaped_content_bypasses_at_local_origin(self):
        """Precondition: the bypass exists and is reachable normally."""
        from mcp_server.core.write_gate import determine_bypass

        bypass, reason = determine_bypass(
            False, self.ERROR_SHAPED, [], origin=ORIGIN_LOCAL_ACTION
        )
        assert bypass is True
        assert reason == "bypass_error"

    def test_error_shaped_content_is_refused_at_network_origin(self):
        from mcp_server.core.write_gate import determine_bypass

        bypass, reason = determine_bypass(
            False, self.ERROR_SHAPED, [], origin=ORIGIN_NETWORK
        )
        assert bypass is False, (
            "network-origin content claimed bypass_error — a fetched page can "
            "install itself in durable memory by containing a traceback"
        )
        assert reason is None

    def test_decision_shaped_content_bypasses_at_local_origin(self):
        from mcp_server.core.write_gate import determine_bypass

        bypass, reason = determine_bypass(
            False, self.DECISION_SHAPED, [], origin=ORIGIN_LOCAL_ACTION
        )
        assert bypass is True
        assert reason == "bypass_decision"

    def test_decision_shaped_content_is_refused_at_network_origin(self):
        from mcp_server.core.write_gate import determine_bypass

        bypass, reason = determine_bypass(
            False, self.DECISION_SHAPED, [], origin=ORIGIN_NETWORK
        )
        assert bypass is False, (
            "network-origin content claimed bypass_decision — this is the "
            "exact chain in issue #365"
        )
        assert reason is None

    def test_force_still_wins_at_network_origin(self):
        """force is an out-of-band human signal, not content-derived."""
        from mcp_server.core.write_gate import determine_bypass

        bypass, reason = determine_bypass(
            True, self.DECISION_SHAPED, [], origin=ORIGIN_NETWORK
        )
        assert (bypass, reason) == (True, "forced")

    def test_deliberate_write_class_still_wins_at_network_origin(self):
        from mcp_server.core.write_gate import determine_bypass

        bypass, reason = determine_bypass(
            False,
            "nothing special",
            [],
            write_class="deliberate",
            origin=ORIGIN_NETWORK,
        )
        assert (bypass, reason) == (True, "bypass_write_class_deliberate")

    def test_important_tag_still_wins_at_network_origin(self):
        """Tags are machine-set by the hook, not derived from fetched text.

        _build_tags adds only auto-captured / tool:<name> / error /
        test-result / success — never important or critical — so the tag
        bypass is not reachable from content and stays available.
        """
        from mcp_server.core.write_gate import determine_bypass

        bypass, reason = determine_bypass(
            False, "nothing special", ["important"], origin=ORIGIN_NETWORK
        )
        assert (bypass, reason) == (True, "bypass_important_tag")

    def test_a_caller_that_names_no_origin_is_refused_the_content_bypass(self):
        """The cost of the allowlist, stated as a test rather than discovered.

        A caller that passes no origin gets ORIGIN_UNKNOWN and no longer buys a
        content-derived bypass. That is the intended trade: an unclassified
        channel might be off-machine, and a rejected write is cheaper than a
        fetched page installing itself into durable cross-session memory.

        Nothing legitimate loses out. An explicit `remember` resolves to
        ORIGIN_DELIBERATE (see handlers/remember.py), the auto-capture hook
        always reports its producing tool, and the out-of-band escapes —
        `force` and an important/critical tag — remain valid at any origin.
        """
        from mcp_server.core.write_gate import determine_bypass

        assert determine_bypass(False, self.ERROR_SHAPED, []) == (False, None)
        assert determine_bypass(False, self.DECISION_SHAPED, []) == (False, None)

    def test_a_deliberate_origin_keeps_the_content_bypass(self):
        """The companion: what an explicit `remember` resolves to still works."""
        from mcp_server.core.write_gate import determine_bypass

        assert determine_bypass(
            False, self.ERROR_SHAPED, [], origin=ORIGIN_DELIBERATE
        ) == (True, "bypass_error")
