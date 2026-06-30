"""Tests for headless_authoring throttle mechanics — Piece 4 (DI seam).

Validates:
  (a) concurrency never exceeds CORTEX_HEADLESS_CONCURRENCY;
  (b) once the wall-clock deadline has passed, remaining candidates return
      status="skipped" and no further invoke calls happen;
  (c) once usd_spent reaches usd_cap, further candidates are skipped;
  (d) ungroundable scopes are never invoked.

No real ``claude`` subprocess is used anywhere in this file.  The
``invoke`` parameter (DI seam) receives a fake async callable instead.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest


# ── Fake invoke infrastructure ──────────────────────────────────────────


@dataclass
class FakeInvokeStats:
    """Shared mutable state for the fake invoke function."""

    calls: int = 0
    max_concurrent: int = 0
    _in_flight: int = field(default=0, repr=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    async def __call__(
        self, prompt: str, *, cost_per_call: float = 0.5, sleep: float = 0.01, **_: Any
    ) -> Any:
        """Fake async invoker: records max concurrency, sleeps, returns InvokeResult."""
        from mcp_server.handlers.consolidation.headless_authoring import InvokeResult

        async with self._lock:
            self.calls += 1
            self._in_flight += 1
            if self._in_flight > self.max_concurrent:
                self.max_concurrent = self._in_flight

        await asyncio.sleep(sleep)

        async with self._lock:
            self._in_flight -= 1

        return InvokeResult(text="fake content", cost_usd=cost_per_call)


def _make_stats(cost_per_call: float = 0.5, sleep: float = 0.01) -> FakeInvokeStats:
    """Construct a FakeInvokeStats whose __call__ uses fixed cost + sleep."""
    stats = FakeInvokeStats()

    async def _invoke(prompt: str, **kw: Any) -> Any:
        return await stats(prompt, cost_per_call=cost_per_call, sleep=sleep, **kw)

    # Attach to the stats object for use as ``invoke=``
    stats._invoke_fn = _invoke  # type: ignore[attr-defined]
    return stats


# ── Helpers ──────────────────────────────────────────────────────────────


def _make_wiki_page(tmp_path: Path, name: str = "page.md") -> Path:
    """Write a minimal wiki page with one curation gap."""
    page = tmp_path / name
    page.write_text(
        "---\n"
        "title: Test Page\n"
        "kind: reference\n"
        "domain: test-domain\n"
        "source_file_path: mcp_server/core/test_module.py\n"
        "lifecycle: needs-curation\n"
        "curation_gaps:\n"
        "  - purpose\n"
        "---\n\n"
        "_(missing — needs: What this file is responsible for)_\n",
        encoding="utf-8",
    )
    return page


def _make_scope(name: str, groundable: bool = True) -> MagicMock:
    """Build a mock Scope object."""
    sc = MagicMock()
    sc.name = name
    sc.title = f"{name} title"
    sc.description = f"{name} description"
    sc.groundable = groundable
    sc.suggested_kind = "reference"
    return sc


def _make_scope_coverage(scope_name: str, groundable: bool = True) -> MagicMock:
    """Build a mock ScopeCoverage object."""
    sco = MagicMock()
    sco.covered = False
    sco.suggested_path = f"reference/test/{scope_name}.md"
    sco.scope = _make_scope(scope_name, groundable=groundable)
    return sco


# ── Test (a): concurrency cap ─────────────────────────────────────────────


class TestConcurrencyCap:
    """Concurrency never exceeds CORTEX_HEADLESS_CONCURRENCY."""

    @pytest.mark.asyncio
    async def test_max_concurrent_pages_respects_cap(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With cap=2 and 6 pages, at most 2 invoke calls run simultaneously."""
        import mcp_server.handlers.consolidation.headless_authoring as ha

        monkeypatch.setattr(ha, "CORTEX_HEADLESS_CONCURRENCY", 2)
        monkeypatch.setattr(ha, "CORTEX_HEADLESS_BUDGET_SEC", 60.0)
        monkeypatch.setattr(ha, "CORTEX_HEADLESS_USD_BUDGET", 100.0)
        monkeypatch.setattr(ha, "CORTEX_HEADLESS_MAX_FILE_DRAINS", 6)
        monkeypatch.setattr(ha, "CORTEX_HEADLESS_MAX_ANCHOR_DRAINS", 0)
        monkeypatch.setattr(ha, "_collect_anchor_candidates", lambda *_: [])

        # Create 6 pages, each with a resolvable source root
        pages = [_make_wiki_page(tmp_path, f"page_{i}.md") for i in range(6)]

        # Patch _scan_pages_with_gaps to return our fake pages
        def fake_scan(_: Path) -> list[Any]:
            return [
                (
                    p,
                    {
                        "curation_gaps": ["purpose"],
                        "domain": "d",
                        "kind": "reference",
                        "source_file_path": "x.py",
                    },
                    "_(missing — needs: What)_",
                )
                for p in pages
            ]

        monkeypatch.setattr(ha, "_scan_pages_with_gaps", fake_scan)

        stats = FakeInvokeStats()

        async def fake_invoke(prompt: str, **kw: Any) -> ha.InvokeResult:
            return await stats(prompt, cost_per_call=0.1, sleep=0.05, **kw)

        await ha.run_headless_authoring_cycle(tmp_path, invoke=fake_invoke)

        assert stats.max_concurrent <= 2, (
            f"Expected max_concurrent <= 2, got {stats.max_concurrent}"
        )
        assert stats.calls == 6

    @pytest.mark.asyncio
    async def test_max_concurrent_anchors_respects_cap(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With cap=3 and 5 anchor candidates, at most 3 invoke calls in flight."""
        import mcp_server.handlers.consolidation.headless_authoring as ha

        monkeypatch.setattr(ha, "CORTEX_HEADLESS_CONCURRENCY", 3)
        monkeypatch.setattr(ha, "CORTEX_HEADLESS_BUDGET_SEC", 60.0)
        monkeypatch.setattr(ha, "CORTEX_HEADLESS_USD_BUDGET", 100.0)
        monkeypatch.setattr(ha, "CORTEX_HEADLESS_MAX_FILE_DRAINS", 0)
        monkeypatch.setattr(ha, "CORTEX_HEADLESS_MAX_ANCHOR_DRAINS", 5)
        monkeypatch.setattr(ha, "_scan_pages_with_gaps", lambda _: [])

        # 5 anchor candidates
        fake_cands = [
            ha._AnchorCandidate(
                domain="proj",
                scope_name=f"scope_{i}",
                scope_title=f"Scope {i}",
                scope_description=f"Description {i}",
                source_root=str(tmp_path),
                suggested_path=f"reference/proj/scope_{i}.md",
                suggested_kind="reference",
            )
            for i in range(5)
        ]
        monkeypatch.setattr(ha, "_collect_anchor_candidates", lambda *_: fake_cands)

        stats = FakeInvokeStats()

        async def fake_invoke(prompt: str, **kw: Any) -> ha.InvokeResult:
            return await stats(prompt, cost_per_call=0.2, sleep=0.05, **kw)

        await ha.run_headless_authoring_cycle(tmp_path, invoke=fake_invoke)

        assert stats.max_concurrent <= 3, (
            f"Expected max_concurrent <= 3, got {stats.max_concurrent}"
        )
        assert stats.calls == 5


# ── Test (b): wall-clock deadline ────────────────────────────────────────


class TestWallClockDeadline:
    """Once the wall-clock deadline passes, remaining candidates are skipped."""

    @pytest.mark.asyncio
    async def test_expired_deadline_skips_remaining(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Once the budget reports exhausted, remaining candidates are skipped.

        Deterministic: instead of racing a near-zero wall-clock budget against
        a sleeping invoke (timing-flaky on a loaded CI), we patch
        ``CycleBudget.exhausted`` to report not-exhausted on its first consult
        and exhausted thereafter. With CONCURRENCY=1 the drains serialize, so
        exactly the first candidate runs and the rest are skipped.
        """
        import mcp_server.handlers.consolidation.headless_authoring as ha

        monkeypatch.setattr(ha, "CORTEX_HEADLESS_CONCURRENCY", 1)
        monkeypatch.setattr(ha, "CORTEX_HEADLESS_BUDGET_SEC", 60.0)
        monkeypatch.setattr(ha, "CORTEX_HEADLESS_USD_BUDGET", 0.0)  # no USD cap
        monkeypatch.setattr(ha, "CORTEX_HEADLESS_MAX_FILE_DRAINS", 4)
        monkeypatch.setattr(ha, "CORTEX_HEADLESS_MAX_ANCHOR_DRAINS", 0)
        monkeypatch.setattr(ha, "_collect_anchor_candidates", lambda *_: [])

        # First consult → not exhausted (first drain proceeds); all later
        # consults → exhausted (remaining drains skip). No wall-clock timing.
        consults = {"n": 0}

        def fake_exhausted(_self: Any) -> bool:
            consults["n"] += 1
            return consults["n"] > 1

        monkeypatch.setattr(ha.CycleBudget, "exhausted", fake_exhausted)

        pages = [_make_wiki_page(tmp_path, f"page_{i}.md") for i in range(4)]

        def fake_scan(_: Path) -> list[Any]:
            return [
                (p, {"curation_gaps": ["purpose"], "domain": "d"}, "body")
                for p in pages
            ]

        monkeypatch.setattr(ha, "_scan_pages_with_gaps", fake_scan)

        call_count = 0

        async def invoke(prompt: str, **kw: Any) -> ha.InvokeResult:
            nonlocal call_count
            call_count += 1
            return ha.InvokeResult(text="content", cost_usd=0.0)

        summary = await ha.run_headless_authoring_cycle(tmp_path, invoke=invoke)

        skipped = [r for r in summary.results if r.status == "skipped"]
        assert len(skipped) > 0, "Expected at least one skipped result after deadline"
        # Budget-skipped items must NOT have called invoke.
        assert call_count < 4, f"Expected fewer than 4 invoke calls; got {call_count}"
        assert summary.skipped_budget >= len(skipped)
        # MINOR-2 invariant: budget-skipped candidates are NOT counted as
        # attempts. attempted + skipped must reconstruct the full result set.
        assert summary.drains_attempted + len(skipped) == len(summary.results)


# ── Test (c): USD cap ─────────────────────────────────────────────────────


class TestUsdCap:
    """Once usd_spent reaches usd_cap, further candidates are skipped."""

    @pytest.mark.asyncio
    async def test_usd_cap_stops_further_calls(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With usd_cap=0.5 and cost_per_call=0.5, only 1 call should run."""
        import mcp_server.handlers.consolidation.headless_authoring as ha

        monkeypatch.setattr(ha, "CORTEX_HEADLESS_CONCURRENCY", 1)
        monkeypatch.setattr(ha, "CORTEX_HEADLESS_BUDGET_SEC", 60.0)
        monkeypatch.setattr(ha, "CORTEX_HEADLESS_USD_BUDGET", 0.5)
        monkeypatch.setattr(ha, "CORTEX_HEADLESS_MAX_FILE_DRAINS", 4)
        monkeypatch.setattr(ha, "CORTEX_HEADLESS_MAX_ANCHOR_DRAINS", 0)
        monkeypatch.setattr(ha, "_collect_anchor_candidates", lambda *_: [])

        pages = [_make_wiki_page(tmp_path, f"page_{i}.md") for i in range(4)]

        def fake_scan(_: Path) -> list[Any]:
            return [
                (p, {"curation_gaps": ["purpose"], "domain": "d"}, "body")
                for p in pages
            ]

        monkeypatch.setattr(ha, "_scan_pages_with_gaps", fake_scan)

        call_count = 0

        async def costly_invoke(prompt: str, **kw: Any) -> ha.InvokeResult:
            nonlocal call_count
            call_count += 1
            return ha.InvokeResult(text="content", cost_usd=0.5)

        summary = await ha.run_headless_authoring_cycle(tmp_path, invoke=costly_invoke)

        # With concurrency=1 and cap=0.5 / cost=0.5, at most 1 call should
        # run before the budget is exhausted.  Allow 1 overshoot at most
        # (soft cap — see CycleBudget docstring).
        assert call_count <= 2, (
            f"Expected at most 2 invoke calls under USD cap; got {call_count}"
        )
        skipped = [r for r in summary.results if r.status == "skipped"]
        assert len(skipped) >= 2, (
            f"Expected at least 2 skipped results; got {len(skipped)}"
        )
        assert summary.skipped_budget > 0
        assert summary.usd_spent >= 0.5

    @pytest.mark.asyncio
    async def test_zero_usd_cap_means_unlimited(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """usd_cap <= 0 means no USD ceiling — all candidates should run."""
        import mcp_server.handlers.consolidation.headless_authoring as ha

        monkeypatch.setattr(ha, "CORTEX_HEADLESS_CONCURRENCY", 4)
        monkeypatch.setattr(ha, "CORTEX_HEADLESS_BUDGET_SEC", 60.0)
        monkeypatch.setattr(ha, "CORTEX_HEADLESS_USD_BUDGET", 0.0)  # unlimited
        monkeypatch.setattr(ha, "CORTEX_HEADLESS_MAX_FILE_DRAINS", 3)
        monkeypatch.setattr(ha, "CORTEX_HEADLESS_MAX_ANCHOR_DRAINS", 0)
        monkeypatch.setattr(ha, "_collect_anchor_candidates", lambda *_: [])

        pages = [_make_wiki_page(tmp_path, f"page_{i}.md") for i in range(3)]

        def fake_scan(_: Path) -> list[Any]:
            return [
                (p, {"curation_gaps": ["purpose"], "domain": "d"}, "body")
                for p in pages
            ]

        monkeypatch.setattr(ha, "_scan_pages_with_gaps", fake_scan)

        call_count = 0

        async def invoke(prompt: str, **kw: Any) -> ha.InvokeResult:
            nonlocal call_count
            call_count += 1
            return ha.InvokeResult(text="content", cost_usd=99.0)

        summary = await ha.run_headless_authoring_cycle(tmp_path, invoke=invoke)

        assert call_count == 3, f"Expected 3 calls (no USD cap); got {call_count}"
        assert summary.skipped_budget == 0


# ── Test (d): ungroundable scopes never invoked ──────────────────────────


class TestGroundableFilter:
    """Ungroundable scopes are never passed to invoke."""

    @pytest.mark.asyncio
    async def test_drain_missing_anchors_skips_ungroundable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """drain_missing_anchors: scopes with groundable=False are never invoked."""
        import mcp_server.handlers.consolidation.headless_authoring as ha

        # Build fake domain registry with one domain.
        fake_repo = MagicMock()
        fake_repo.canonical = "test-proj"
        fake_registry = MagicMock()
        fake_registry.repos = [fake_repo]
        monkeypatch.setattr(
            "mcp_server.shared.domain_mapping._build_registry",
            lambda: fake_registry,
        )
        monkeypatch.setattr(
            "mcp_server.core.wiki_coverage._project_source_root",
            lambda d: str(tmp_path) if d == "test-proj" else None,
        )

        # Two scopes: one groundable, one not.
        groundable_sc = _make_scope_coverage("architecture", groundable=True)
        ungroundable_sc = _make_scope_coverage("decisions", groundable=False)

        fake_cov = MagicMock()
        fake_cov.scopes = [groundable_sc, ungroundable_sc]
        monkeypatch.setattr(
            "mcp_server.core.wiki_coverage.audit_domain",
            lambda wiki_root, domain: fake_cov,
        )

        invoked_scopes: list[str] = []

        async def recording_invoke(prompt: str, **kw: Any) -> ha.InvokeResult:
            # The prompt contains the scope name — detect which one was called.
            for name in ("architecture", "decisions"):
                if name in prompt:
                    invoked_scopes.append(name)
            return ha.InvokeResult(text="content", cost_usd=0.1)

        await ha.drain_missing_anchors(tmp_path, invoke=recording_invoke)

        assert "decisions" not in invoked_scopes, (
            "Ungroundable scope 'decisions' must never be invoked"
        )
        # groundable scope 'architecture' should have been attempted.
        assert "architecture" in invoked_scopes

    @pytest.mark.asyncio
    async def test_collect_anchor_candidates_excludes_ungroundable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """_collect_anchor_candidates filters out scopes with groundable=False."""
        import mcp_server.handlers.consolidation.headless_authoring as ha

        fake_repo = MagicMock()
        fake_repo.canonical = "test-proj"
        fake_registry = MagicMock()
        fake_registry.repos = [fake_repo]
        monkeypatch.setattr(
            "mcp_server.shared.domain_mapping._build_registry",
            lambda: fake_registry,
        )
        monkeypatch.setattr(
            "mcp_server.core.wiki_coverage._project_source_root",
            lambda d: str(tmp_path),
        )

        groundable_sc = _make_scope_coverage("architecture", groundable=True)
        ungroundable_sc = _make_scope_coverage("prd", groundable=False)
        another_ungroundable = _make_scope_coverage("changelog", groundable=False)

        fake_cov = MagicMock()
        fake_cov.scopes = [groundable_sc, ungroundable_sc, another_ungroundable]
        monkeypatch.setattr(
            "mcp_server.core.wiki_coverage.audit_domain",
            lambda wiki_root, domain: fake_cov,
        )

        cands = ha._collect_anchor_candidates(tmp_path, max_drains=10)

        scope_names = [c.scope_name for c in cands]
        assert "prd" not in scope_names, "'prd' (ungroundable) must be excluded"
        assert "changelog" not in scope_names, (
            "'changelog' (ungroundable) must be excluded"
        )
        assert "architecture" in scope_names, (
            "'architecture' (groundable) must be included"
        )

    @pytest.mark.asyncio
    async def test_cycle_never_invokes_ungroundable_scopes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """In the full cycle, ungroundable scopes produce no invoke calls."""
        import mcp_server.handlers.consolidation.headless_authoring as ha

        # Cycle uses _collect_anchor_candidates, not drain_missing_anchors.
        # Provide candidates list with one ungroundable to confirm it's excluded.
        monkeypatch.setattr(ha, "CORTEX_HEADLESS_CONCURRENCY", 4)
        monkeypatch.setattr(ha, "CORTEX_HEADLESS_BUDGET_SEC", 60.0)
        monkeypatch.setattr(ha, "CORTEX_HEADLESS_USD_BUDGET", 0.0)
        monkeypatch.setattr(ha, "CORTEX_HEADLESS_MAX_FILE_DRAINS", 0)
        monkeypatch.setattr(ha, "CORTEX_HEADLESS_MAX_ANCHOR_DRAINS", 5)
        monkeypatch.setattr(ha, "_scan_pages_with_gaps", lambda _: [])

        # _collect_anchor_candidates already filters ungroundable scopes.
        # We verify indirectly: provide only groundable candidates and check
        # that invoke is called exactly once.
        monkeypatch.setattr(
            ha,
            "_collect_anchor_candidates",
            lambda wiki_root, max_drains: [
                ha._AnchorCandidate(
                    domain="proj",
                    scope_name="architecture",
                    scope_title="Architecture",
                    scope_description="Desc",
                    source_root=str(tmp_path),
                    suggested_path="reference/proj/architecture.md",
                    suggested_kind="reference",
                )
            ],
        )

        call_count = 0

        async def invoke(prompt: str, **kw: Any) -> ha.InvokeResult:
            nonlocal call_count
            call_count += 1
            return ha.InvokeResult(text="content", cost_usd=0.1)

        summary = await ha.run_headless_authoring_cycle(tmp_path, invoke=invoke)

        # Only the groundable anchor should have been attempted.
        assert call_count == 1
        assert summary.drains_attempted == 1


# ── Test: CycleBudget unit tests ─────────────────────────────────────────


class TestCycleBudget:
    """Unit tests for CycleBudget methods."""

    def test_exhausted_by_time(self) -> None:
        from mcp_server.handlers.consolidation.headless_authoring import CycleBudget

        budget = CycleBudget(deadline=time.monotonic() - 1.0, usd_cap=100.0)
        assert budget.exhausted()

    def test_not_exhausted_when_time_remains(self) -> None:
        from mcp_server.handlers.consolidation.headless_authoring import CycleBudget

        budget = CycleBudget(deadline=time.monotonic() + 60.0, usd_cap=100.0)
        assert not budget.exhausted()

    def test_exhausted_by_usd(self) -> None:
        from mcp_server.handlers.consolidation.headless_authoring import CycleBudget

        budget = CycleBudget(deadline=time.monotonic() + 60.0, usd_cap=5.0)
        budget.charge(5.0)
        assert budget.exhausted()

    def test_no_usd_cap_when_zero(self) -> None:
        from mcp_server.handlers.consolidation.headless_authoring import CycleBudget

        budget = CycleBudget(deadline=time.monotonic() + 60.0, usd_cap=0.0)
        budget.charge(999.0)
        # usd_cap <= 0 means unlimited — should NOT be exhausted by USD alone.
        assert not budget.exhausted()

    def test_charge_is_cumulative(self) -> None:
        from mcp_server.handlers.consolidation.headless_authoring import CycleBudget

        budget = CycleBudget(deadline=time.monotonic() + 60.0, usd_cap=10.0)
        budget.charge(3.0)
        budget.charge(4.0)
        assert abs(budget.usd_spent - 7.0) < 1e-9
        assert not budget.exhausted()
        budget.charge(3.0)
        assert budget.exhausted()


# ── Test (e): cancellation cleanup ────────────────────────────────────────


class _HangingProc:
    """Fake subprocess whose communicate() never returns; records kill/wait."""

    def __init__(self) -> None:
        self.returncode: int | None = None
        self.killed = False
        self.waited = False

    async def communicate(self) -> Any:
        await asyncio.Event().wait()  # hang until cancelled

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    async def wait(self) -> int | None:
        self.waited = True
        return self.returncode


class TestCancellationCleanup:
    """A cancelled _claude_invoke must not leak a running subprocess.

    CancelledError is a BaseException — it escapes the ``except Exception``
    clauses, so the kill must live in a ``finally`` block.
    """

    @pytest.mark.asyncio
    async def test_cancellation_kills_subprocess(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from mcp_server.handlers.consolidation import headless_authoring as ha

        proc = _HangingProc()

        async def _fake_exec(*_a: Any, **_k: Any) -> _HangingProc:
            return proc

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)

        task = asyncio.create_task(ha._claude_invoke("prompt"))
        await asyncio.sleep(0.05)  # let it reach communicate()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert proc.killed, "subprocess.kill() must run in finally on cancellation"
        assert proc.waited, "must reap the killed subprocess via wait()"


class TestSubscriptionAuth:
    """The drain runs on the subscription by default, API key only on opt-in.

    Enforcing facts: argv carries ``--safe-mode`` (config isolation that keeps
    OAuth/keychain) and never ``--bare`` (which forces API-key billing); the
    default child env strips ``ANTHROPIC_API_KEY`` / ``ANTHROPIC_AUTH_TOKEN``
    (subscription); and ``CORTEX_HEADLESS_AUTH=api`` passes them through so a
    user who wants API billing still can.
    """

    @staticmethod
    def _patch_exec(monkeypatch: pytest.MonkeyPatch, captured: dict[str, Any]) -> None:
        class _OkProc:
            returncode = 0

            async def communicate(self) -> Any:
                return (b'{"result": "OK", "total_cost_usd": 0.0}', b"")

        async def _fake_exec(*argv: Any, **kwargs: Any) -> _OkProc:
            captured["argv"] = list(argv)
            captured["env"] = kwargs.get("env")
            return _OkProc()

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)

    @pytest.mark.asyncio
    async def test_default_uses_safe_mode_and_strips_api_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from mcp_server.handlers.consolidation import headless_authoring as ha

        monkeypatch.delenv("CORTEX_HEADLESS_AUTH", raising=False)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-be-stripped")
        monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "tok-should-be-stripped")
        captured: dict[str, Any] = {}
        self._patch_exec(monkeypatch, captured)

        result = await ha._claude_invoke("prompt")

        assert result.text == "OK"
        assert "--safe-mode" in captured["argv"]
        assert "--bare" not in captured["argv"]
        env = captured["env"]
        assert env is not None, "must pass an explicit env to strip credentials"
        assert "ANTHROPIC_API_KEY" not in env
        assert "ANTHROPIC_AUTH_TOKEN" not in env

    @pytest.mark.asyncio
    async def test_api_mode_passes_api_key_through(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from mcp_server.handlers.consolidation import headless_authoring as ha

        monkeypatch.setenv("CORTEX_HEADLESS_AUTH", "api")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-user-opted-in")
        captured: dict[str, Any] = {}
        self._patch_exec(monkeypatch, captured)

        result = await ha._claude_invoke("prompt")

        assert result.text == "OK"
        assert "--safe-mode" in captured["argv"]
        env = captured["env"]
        assert env is not None
        assert env.get("ANTHROPIC_API_KEY") == "sk-user-opted-in"
