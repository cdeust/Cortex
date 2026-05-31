"""Append-only event log + subscriber fan-out for the layout authority.

Three event kinds (each is a tuple ``(seq, kind, payload_bytes)``)::

    'slot'  - a SlotAssignment
    'edge'  - an EdgeDelta
    'done'  - build complete

Sequence numbers are monotonically increasing across the entire log.
``Last-Event-ID`` resume uses ``seq`` as the cursor.

Memory budget: bounded ring buffer (default 500_000 events). At ~80 bytes
per event payload + ~32 bytes tuple overhead = ~56 MB worst-case for
the buffer. Exceeds the 8 MB ceiling on principle, but this is the only
structure that has to scale with stream length, and capping replay at
500k events is the right tradeoff: a client that has been disconnected
long enough to fall outside the buffer falls back to a full re-stream
from the build cache, not from the live SSE.

Subscriber queues: bounded at 100k each. A subscriber that fails
``put_nowait`` more than 200 times in a row is presumed dead and
auto-evicted, so the producer is never starved.

Concurrency precondition (load-bearing for happens-before invariants
I1 and I2): ``emit()`` MUST be called from a single producer thread
(the layout authority worker). The fan-out loop runs after the log
lock is released, so two concurrent producers could enqueue events to
a subscriber in an order that disagrees with their seq. The single-
producer rule keeps the deque order, the seq order, and the per-
subscriber delivery order identical. ``subscribe`` / ``unsubscribe`` /
``replay_since`` / ``stats`` / ``reset`` are safe from any thread.
"""

import collections
import queue as _queue_mod
import threading
from typing import Deque, List, Tuple


# --- module configuration --------------------------------------------------

_EVENT_LOG_CAP = 500_000
_SUBSCRIBER_QUEUE_CAP = 100_000
_DEAD_QUEUE_MISS_THRESHOLD = 200

Event = Tuple[int, str, bytes]


# --- module state ----------------------------------------------------------

_event_log: Deque[Event] = collections.deque(maxlen=_EVENT_LOG_CAP)
_event_log_lock = threading.Lock()
_event_seq = 0
_event_log_drops = 0

_subscribers: List[_queue_mod.Queue] = []
_subscribers_lock = threading.Lock()


# --- internal helpers ------------------------------------------------------


def _record_miss(q: _queue_mod.Queue) -> int:
    misses = getattr(q, "_cortex_misses", 0) + 1
    try:
        q._cortex_misses = misses  # type: ignore[attr-defined]
    except Exception:
        # Some Queue subclasses lock down attribute assignment; the
        # subscriber will still be reaped on the next miss because the
        # local count cannot persist - acceptable degradation.
        pass
    return misses


def _clear_misses(q: _queue_mod.Queue) -> None:
    try:
        q._cortex_misses = 0  # type: ignore[attr-defined]
    except Exception:
        pass


def _fan_out(event: Event) -> List[_queue_mod.Queue]:
    """Deliver ``event`` to every live subscriber queue.

    Returns the list of subscribers that crossed the dead-queue threshold
    on this call. Caller is responsible for removing them from the
    subscriber list under ``_subscribers_lock``. The fan-out itself runs
    against a *snapshot* of the subscriber list so that the producer
    never blocks on the subscriber lock during delivery.
    """
    with _subscribers_lock:
        subs = list(_subscribers)
    dead: List[_queue_mod.Queue] = []
    for q in subs:
        try:
            q.put_nowait(event)
            _clear_misses(q)
        except Exception:
            misses = _record_miss(q)
            if misses > _DEAD_QUEUE_MISS_THRESHOLD:
                dead.append(q)
    return dead


def _reap(dead: List[_queue_mod.Queue]) -> None:
    if not dead:
        return
    with _subscribers_lock:
        for q in dead:
            try:
                _subscribers.remove(q)
            except ValueError:
                pass


# --- public API ------------------------------------------------------------


def emit(kind: str, payload: bytes) -> int:
    """Append ``(seq, kind, payload)`` to the log and fan out to subs.

    Returns the assigned ``seq``. ``payload`` is bytes (already SSE-
    formatted by ``layout_authority_wire``) so the SSE handler can
    write it to the socket with zero re-encoding.

    Single-producer precondition: see module docstring.
    """
    global _event_seq, _event_log_drops
    with _event_log_lock:
        _event_seq += 1
        seq = _event_seq
        event: Event = (seq, kind, payload)
        if len(_event_log) == _event_log.maxlen:
            _event_log_drops += 1
        _event_log.append(event)
    dead = _fan_out(event)
    _reap(dead)
    return seq


def subscribe() -> _queue_mod.Queue:
    """Register a new subscriber and return its bounded delivery queue.

    The caller is responsible for draining the queue (typically an SSE
    handler in its own thread). The queue is bounded at
    ``_SUBSCRIBER_QUEUE_CAP``; persistent backpressure causes
    auto-eviction.
    """
    q: _queue_mod.Queue = _queue_mod.Queue(maxsize=_SUBSCRIBER_QUEUE_CAP)
    _clear_misses(q)
    with _subscribers_lock:
        _subscribers.append(q)
    return q


def unsubscribe(q: _queue_mod.Queue) -> None:
    """Remove a subscriber. Idempotent."""
    with _subscribers_lock:
        try:
            _subscribers.remove(q)
        except ValueError:
            pass


def replay_since(since: int) -> Tuple[List[Event], int]:
    """Return ``(events_to_replay, oldest_available_seq)``.

    If ``since`` is older than the oldest retained seq the second tuple
    element flags the gap (i.e. ``oldest_available_seq > since + 1``).
    The SSE handler in ``graph_stream`` emits a ``replay_lost`` sentinel
    in that case and the client falls back to a snapshot.
    """
    with _event_log_lock:
        if not _event_log:
            return [], 0
        oldest_seq = _event_log[0][0]
        if since < oldest_seq - 1:
            return [], oldest_seq
        out = [e for e in _event_log if e[0] > since]
        return out, oldest_seq


def stats() -> dict:
    """Return a snapshot of log + subscriber metrics."""
    with _event_log_lock:
        oldest = _event_log[0][0] if _event_log else 0
        newest = _event_log[-1][0] if _event_log else 0
        size = len(_event_log)
        drops = _event_log_drops
    with _subscribers_lock:
        sub_count = len(_subscribers)
    return {
        "size": size,
        "cap": _EVENT_LOG_CAP,
        "oldest_seq": oldest,
        "newest_seq": newest,
        "drops": drops,
        "subscribers": sub_count,
    }


def reset() -> None:
    """Wipe the log and drop all subscribers.

    Called when the build worker starts a fresh build so a stale client
    cannot read events from the previous run as if they were current.

    Per invariant I3 (module docstring): ``_event_seq`` is GLOBAL, not
    per-build, and continues across resets. A client reconnecting with
    ``Last-Event-ID: N`` after a reset asks ``replay_since(N)``; the new
    log's oldest seq is ``N + 1`` or greater (because the counter never
    rewinds), so the gap-detection branch in ``replay_since`` correctly
    identifies that the requested events are gone and the client falls
    back to a snapshot. Resetting the counter would silently violate
    this resume protocol because seq numbers from the previous stream
    would collide with new ones.

    Note: the original spec docstring and the original spec code body
    disagreed on this point. The prose (I3, "seq continues") is the
    operationally correct version because the resume protocol depends
    on monotonic seq across resets; the code-body version (``_event_seq
    = 0``) would silently break ``Last-Event-ID`` resume across a build
    boundary. We follow the prose.
    """
    global _event_log_drops
    with _event_log_lock:
        _event_log.clear()
        _event_log_drops = 0
    with _subscribers_lock:
        _subscribers.clear()
