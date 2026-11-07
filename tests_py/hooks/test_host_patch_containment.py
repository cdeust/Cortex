"""An apply_patch path never makes the hook read a file outside the project.

GHSA-pw64-v3mg-xxmm: the Codex apply_patch translation joined the patch path with
the working directory and resolved it without checking containment, so an
Update or Delete of `../../../etc/hostname` (or of a symlink leading out) read
that file as the operation's preimage. Each case puts a real secret outside the
project and checks that no event, and so no copy of the secret, is produced.
"""

from __future__ import annotations

import os

import pytest

from mcp_server.hooks.host_event import HostEventError
from mcp_server.hooks.host_patch import patch_events

SECRET = "outside-the-project secret"
# The exact message: a reworded or wrapped one is a different contract.
ESCAPE = r"^Patch path escapes the working directory$"


def _event(cwd, patch):
    command = "*** Begin Patch\n" + patch + "\n*** End Patch"
    return {"cwd": str(cwd), "tool_input": {"command": command}}


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "inside.txt").write_text("old line\n", encoding="utf-8")
    (tmp_path / "secret.txt").write_text(SECRET + "\n", encoding="utf-8")
    return root


@pytest.mark.parametrize("operation", ["Update File", "Delete File"])
def test_a_relative_traversal_is_refused(project, operation):
    patch = f"*** {operation}: ../secret.txt\n-{SECRET}\n+x"
    if operation == "Delete File":
        patch = f"*** {operation}: ../secret.txt"
    with pytest.raises(HostEventError, match=ESCAPE):
        patch_events(_event(project, patch))


def test_an_absolute_path_outside_is_refused(project):
    outside = project.parent / "secret.txt"
    with pytest.raises(HostEventError, match=ESCAPE):
        patch_events(_event(project, f"*** Delete File: {outside}"))


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="no symlinks")
def test_a_symlink_leading_out_is_refused(project):
    (project / "link.txt").symlink_to(project.parent / "secret.txt")
    with pytest.raises(HostEventError, match=ESCAPE):
        patch_events(_event(project, "*** Delete File: link.txt"))


def test_a_path_inside_the_project_is_still_translated(project):
    events = patch_events(
        _event(project, "*** Update File: inside.txt\n@@\n-old line\n+new line")
    )
    assert [e["tool_input"]["file_path"] for e in events] == [
        str((project / "inside.txt").resolve())
    ]
