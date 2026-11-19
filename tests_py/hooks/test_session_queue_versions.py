"""A later version of a received Codex rollout is a new job (#716).

source: ADR-1144"""

from unittest.mock import patch

from mcp_server.infrastructure.transcript_fingerprint import transcript_fingerprint
from tests_py.hooks.test_session_queue import queue  # noqa: F401 (fixture)


def test_a_later_version_of_a_received_rollout_reaches_the_worker(queue, tmp_path):  # noqa: F811
    """A rollout that ended again with turns appended or an earlier turn
    rewritten reaches the lifecycle; the same bytes stay a replay."""
    root = queue.queue_root()
    rollout = tmp_path / "rollout-a.jsonl"
    event = {"session_id": "s", "transcript_path": str(rollout)}
    versions = [b'{"turn": 1}\n', b'{"turn": 1}\n{"turn": 2}\n', b'{"turn": 9}\n']
    with patch.object(queue.subprocess, "run") as run:
        run.return_value.returncode = 0
        for content in versions:
            rollout.write_bytes(content)
            queue.enqueue(root, event)
            queue.drain(root)
            queue.enqueue(root, event)
            queue.drain(root)
    assert run.call_count == len(versions)
    assert len(list((root / "completed").glob("*.json"))) == len(versions)
    assert not list(root.glob("*.json"))


def test_a_version_queued_behind_a_pending_job_is_its_own_job(queue, tmp_path):  # noqa: F811
    """A second version is not merged into the job still waiting for the
    drain. source: ADR-1144 (decision 3)"""
    root = queue.queue_root()
    rollout = tmp_path / "rollout-a.jsonl"
    event = {"session_id": "s", "transcript_path": str(rollout)}
    rollout.write_bytes(b"first\n")
    first = queue.enqueue(root, event)
    rollout.write_bytes(b"first\nsecond\n")
    second = queue.enqueue(root, event)
    assert first != second
    assert sorted(p.stem for p in root.glob("*.json")) == sorted([first, second])


def test_job_name_keys_the_version_on_the_lifecycle_fingerprint(queue, tmp_path):  # noqa: F811
    """The intake hashes the bytes the lifecycle fingerprints, without
    mcp_server; no readable transcript keeps the ADR-1141 name.
    source: ADR-1144 (decision 1)"""
    rollout = tmp_path / "rollout-a.jsonl"
    for content in (b"", b"x" * ((1 << 20) + 7)):
        rollout.write_bytes(content)
        event = {"session_id": "s", "transcript_path": str(rollout)}
        sha = transcript_fingerprint(str(rollout))["sha256"]
        assert queue.job_name(event) == f"{queue.job_key(event)}-{sha[:32]}"
    for path in (None, "", 3, str(tmp_path / "missing.jsonl"), str(tmp_path)):
        event = {"session_id": "s", "transcript_path": path}
        assert queue.job_name(event) == queue.job_key(event)
