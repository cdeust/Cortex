# ruff: noqa: F811 (the queue fixture is imported, then requested by name)
"""A later version of a received Codex rollout reaches the lifecycle (#716).

source: ADR-1145"""

import json
from unittest.mock import patch

from mcp_server.infrastructure.transcript_fingerprint import transcript_fingerprint
from tests_py.hooks.test_session_queue import queue  # noqa: F401 (fixture)


def _deliver(queue, root, rollout, versions):
    event = {"session_id": "s", "transcript_path": str(rollout)}
    with patch.object(queue.subprocess, "run") as run:
        run.return_value.returncode = 0
        for content in versions:
            rollout.write_bytes(content)
            for _ in range(2):  # the second delivery of each version replays
                queue.enqueue(root, event)
                queue.drain(root)
    return run


def test_a_later_version_of_a_received_rollout_reaches_the_worker(queue, tmp_path):
    """Turns appended, then an earlier turn rewritten: one delivery each."""
    root, rollout = queue.queue_root(), tmp_path / "rollout-a.jsonl"
    versions = [b'{"turn": 1}\n', b'{"turn": 1}\n{"turn": 2}\n', b'{"turn": 9}\n']
    run = _deliver(queue, root, rollout, versions)
    assert run.call_count == len(versions)
    receipts = list((root / "completed").glob("*.json"))
    assert len(receipts) == 1
    recorded = json.loads(receipts[0].read_text())["transcript_sha256"]
    assert recorded == transcript_fingerprint(str(rollout))["sha256"]
    assert not list(root.glob("*.json"))


def test_a_rollout_restored_to_an_earlier_version_reaches_the_worker(queue, tmp_path):
    """A, then B, then A again: the replay check compares with the last
    version received, not with every version ever received."""
    root, rollout = queue.queue_root(), tmp_path / "rollout-a.jsonl"
    run = _deliver(queue, root, rollout, [b"a\n", b"b\n", b"a\n"])
    assert run.call_count == 3


def test_intake_persists_the_event_without_reading_the_rollout(queue, tmp_path):
    """The SessionEnd hook has three seconds (hooks.json): the rollout is
    hashed by the detached drain, never before the job is durable."""
    root, rollout = queue.queue_root(), tmp_path / "rollout-a.jsonl"
    rollout.write_bytes(b"x\n")
    event = {"session_id": "s", "transcript_path": str(rollout)}
    real_open = open

    def guarded(file, *args, **kwargs):
        assert str(file) != str(rollout), "intake read the rollout"
        return real_open(file, *args, **kwargs)

    with patch("builtins.open", guarded), patch("io.open", guarded):
        key = queue.enqueue(root, event)
    assert json.loads((root / f"{key}.json").read_text())["event"] == event


def test_a_delivery_behind_a_pending_job_is_queued_beside_it(queue, tmp_path):
    """The pending job may already be reading older bytes; the later
    delivery is its own job and the drain resolves both."""
    root, rollout = queue.queue_root(), tmp_path / "rollout-a.jsonl"
    event = {"session_id": "s", "transcript_path": str(rollout)}
    rollout.write_bytes(b"first\n")
    first = queue.enqueue(root, event)
    second = queue.enqueue(root, event)
    assert first == queue.job_key(event) and second.startswith(f"{first}-")
    with patch.object(queue.subprocess, "run") as run:
        run.return_value.returncode = 0
        queue.drain(root)
    assert run.call_count == 1  # both jobs saw the same bytes
    assert not list(root.glob("*.json"))


def test_a_receipt_without_a_version_lets_a_readable_rollout_through_once(
    queue, tmp_path
):
    """A receipt written before ADR-1145 names no version; a corrupt one
    is treated the same. An event without a rollout replays on any receipt."""
    root, rollout = queue.queue_root(), tmp_path / "rollout-a.jsonl"
    rollout.write_bytes(b"x\n")
    event = {"session_id": "s", "transcript_path": str(rollout)}
    bare = {"session_id": "s"}
    (root / "completed").mkdir()
    for receipt_text, delivered in (("{}", event), ("not json", event)):
        queue.receipt(root / f"{queue.job_key(event)}.json").write_text(receipt_text)
        queue.receipt(root / f"{queue.job_key(bare)}.json").write_text("{}")
        with patch.object(queue.subprocess, "run") as run:
            run.return_value.returncode = 0
            queue.enqueue(root, event)
            queue.enqueue(root, bare)
            queue.drain(root)
            queue.enqueue(root, event)
            queue.drain(root)
        assert [json.loads(c.kwargs["input"]) for c in run.call_args_list] == [
            delivered
        ]


def test_the_drain_hashes_the_bytes_the_lifecycle_fingerprints(queue, tmp_path):
    """The stdlib copy equals transcript_fingerprint; no readable rollout
    has no version, a path with a NUL byte included. source: ADR-1145"""
    rollout, version = tmp_path / "rollout-a.jsonl", queue._sibling("rollout_version")
    for content in (b"", b"x" * ((1 << 20) + 7)):
        rollout.write_bytes(content)
        event = {"session_id": "s", "transcript_path": str(rollout)}
        assert (
            version.version(event, str(tmp_path))
            == transcript_fingerprint(str(rollout))["sha256"]
        )
    unreadable = (None, "", 3, str(tmp_path / "missing.jsonl"), str(tmp_path))
    for path in (*unreadable, "/r/roll\0out.jsonl"):
        assert (
            version.version({"session_id": "s", "transcript_path": path}, "/") is None
        )


def test_a_relative_rollout_is_hashed_from_the_lifecycle_directory(
    queue, tmp_path, monkeypatch
):
    """The drain runs in the queue directory, the lifecycle in the job's
    ``cwd``: a relative rollout is hashed where the lifecycle reads it.
    source: ADR-1146 (decision 1)"""
    root, project = queue.queue_root(), tmp_path / "project"
    project.mkdir()
    event = {"session_id": "s", "transcript_path": "rollout-a.jsonl"}
    with patch.object(queue.subprocess, "run") as run:
        run.return_value.returncode = 0
        for content in (b"a\n", b"b\n", b"b\n"):
            (project / "rollout-a.jsonl").write_bytes(content)
            monkeypatch.chdir(project)
            queue.enqueue(root, event)
            monkeypatch.chdir(root)
            queue.drain(root)
    assert run.call_count == 2


def test_a_job_queued_while_its_identity_is_held_is_drained(queue, tmp_path):
    """The SessionEnd that lands during a delivery is queued beside it; its
    own drain finds the lock busy, so the holding drain passes again.
    source: ADR-1146 (decision 2)"""
    root, rollout = queue.queue_root(), tmp_path / "rollout-a.jsonl"
    event = {"session_id": "s", "transcript_path": str(rollout)}
    rollout.write_bytes(b"a\n")
    queue.enqueue(root, event)

    def lifecycle(*args, **kwargs):
        if run.call_count == 1:  # during the delivery of A
            rollout.write_bytes(b"b\n")
            queue.enqueue(root, event)
            queue.drain(root)  # B's drain: the identity's lock is busy
        return run.return_value

    with patch.object(queue.subprocess, "run", side_effect=lifecycle) as run:
        run.return_value.returncode = 0
        queue.drain(root)
    assert run.call_count == 2
    assert not list(root.glob("*.json"))


def test_a_replay_clears_the_error_of_its_job(queue, tmp_path):
    """A job dropped as a replay leaves no ``.error`` for intake to print.
    source: ADR-1146 (decision 3)"""
    root, rollout = queue.queue_root(), tmp_path / "rollout-a.jsonl"
    rollout.write_bytes(b"a\n")
    event = {"session_id": "s", "transcript_path": str(rollout)}
    with patch.object(queue.subprocess, "run") as run:
        run.return_value.returncode = 0
        queue.enqueue(root, event)
        queue.drain(root)
        key = queue.enqueue(root, event)
        (root / f"{key}.error").write_text("earlier failure")
        queue.drain(root)
    assert run.call_count == 1
    assert not list(root.glob("*.error"))
