"""remember._resolve_domain: which source names the domain of a write (#721).

The order is the contract: a directory inside a known repository, then the
caller's explicit domain (kept as given, ``resolve_explicit_domain``), then the
profile detected for the directory (resolved as a hint), else no domain. Each
collaborator is replaced by a fake that answers only for the exact arguments
the contract passes, so a call with other arguments yields a different domain.

source: issue #721; ADR-1122 (mutation gate on changed functions)"""

from __future__ import annotations

import pytest

from mcp_server.handlers import remember

_PROFILES = {"sentinel": "profiles"}
_REPO_DIR = "/work/known-repo/src"
_OTHER_DIR = "/work/no-repo"


def _detect(context, profiles=None):
    if context == {"cwd": _OTHER_DIR} and profiles is _PROFILES:
        return {"domain": "Profiled"}
    return {"domain": "wrong-arguments"}


@pytest.fixture
def fakes(monkeypatch):
    monkeypatch.setattr(
        remember, "resolve_cwd", lambda d: "known-repo" if d == _REPO_DIR else ""
    )
    monkeypatch.setattr(remember, "load_profiles", lambda: _PROFILES)
    monkeypatch.setattr(remember, "detect_domain", _detect)
    monkeypatch.setattr(remember, "resolve_hint", lambda h: f"hint:{h}")
    return monkeypatch


def test_known_repository_directory_wins(fakes):
    assert remember._resolve_domain(_REPO_DIR, "SciFact") == "known-repo"


def test_explicit_domain_is_kept_when_directory_is_unknown(fakes):
    assert remember._resolve_domain(_OTHER_DIR, "SciFact") == "scifact"


def test_explicit_domain_without_directory(fakes):
    assert remember._resolve_domain("", "SciFact") == "scifact"


def test_detected_profile_is_resolved_as_a_hint(fakes):
    assert remember._resolve_domain(_OTHER_DIR, "") == "hint:Profiled"


@pytest.mark.parametrize("detection", [{}, {"domain": ""}, {"domain": None}])
def test_no_detected_profile_gives_no_domain(fakes, detection):
    fakes.setattr(remember, "detect_domain", lambda context, profiles=None: detection)
    assert remember._resolve_domain(_OTHER_DIR, "") == ""


def test_no_directory_and_no_domain_gives_no_domain(fakes):
    assert remember._resolve_domain("", "") == ""
