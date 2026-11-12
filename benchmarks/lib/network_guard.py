"""A process-wide switch that turns networking off and records each attempt.

Issue #734, slice 6. The offline receipt (``offline_receipt.py``) runs memory
operations with this guard installed before ``mcp_server`` is imported, so
every connection a run tries to open beyond the machine is refused with
``ENETUNREACH``, the error a host with no route returns, and is written down.

What it refuses and what it lets through:

- ``socket.socket.connect`` (raises) and ``connect_ex`` (returns the errno)
  to an address outside the loopback ranges (``127.0.0.0/8``, ``::1``) are
  refused. A Unix socket, and a
  loopback address, are left alone: a local PostgreSQL and asyncio's
  self-pipe are not the network.
- A loopback address that a configured HTTP proxy listens on is refused too:
  a proxy on ``127.0.0.1`` relays to any host, so it is the network. The
  first run of the receipt in a container whose ``HTTPS_PROXY`` is
  ``http://127.0.0.1:<port>`` downloaded FlashRank through it, past a guard
  that allowed every loopback address (issue #734, slice 6).
- ``socket.getaddrinfo`` of any name other than ``localhost`` or a loopback
  literal is refused, so a resolver lookup counts as an attempt even when the
  caller would have stopped there.

- ``subprocess.Popen`` is refused (``EPERM``) and recorded as a ``spawn``
  with the program's base name: a child process is outside this guard, and
  the embedding engine starts its model download in one
  (``embedding_downloads.trigger_background_model_download``), which the
  first receipt let through and still called ``offline``.

Limits, stated in the receipt: the guard covers Python code that goes through
the ``socket`` module (``urllib``, ``requests``, ``httpx``, ``huggingface_hub``,
asyncio). A native extension that opens its own sockets is not covered.

source: issue #734, acceptance item 4 ("Demonstrate memory operations with
networking disabled after provisioning and label fallback behavior")
"""

from __future__ import annotations

import errno
import ipaddress
import os
import socket
import subprocess
import urllib.parse
import urllib.request
from typing import Any

# source: RFC 6890 (loopback 127.0.0.0/8, ::1/128); "localhost" per RFC 6761.
_LOOPBACK_NAMES = frozenset({"localhost"})
_REFUSAL = "network disabled by the offline receipt (issue #734)"


def is_local(host: Any) -> bool:
    """True when ``host`` names this machine: None, ``localhost``, a loopback
    literal. Any other name or address is the network."""
    if host is None:
        return True
    name = host.decode() if isinstance(host, bytes) else str(host)
    if name.lower() in _LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(name.split("%", 1)[0]).is_loopback
    except ValueError:
        return False


def proxy_endpoints() -> frozenset[tuple[str, int]]:
    """``(host, port)`` of every proxy ``urllib`` would use: the ``*_proxy``
    variables, and on macOS and Windows the system settings.

    postcondition: a proxy URL without a port is skipped (no endpoint to
    refuse); ``no_proxy`` is not an endpoint and is ignored."""
    endpoints = set()
    for scheme, url in urllib.request.getproxies().items():
        if scheme == "no":
            continue
        parsed = urllib.parse.urlsplit(url if "//" in url else f"//{url}")
        try:
            port = parsed.port
        except ValueError:
            continue
        if parsed.hostname and port:
            endpoints.add((parsed.hostname.lower(), port))
    return frozenset(endpoints)


def with_resolved(endpoints: frozenset[tuple[str, int]]) -> frozenset[tuple[str, int]]:
    """``endpoints`` plus the addresses each local proxy name resolves to.

    ``connect`` receives an address, not a name: a client that resolves a
    ``localhost`` proxy first connects to ``127.0.0.1``, which a literal
    ``("localhost", port)`` would let through. Only names that ``is_local``
    accepts are resolved (``/etc/hosts``, no resolver traffic); a remote
    proxy is refused as any remote address is. Call before ``install``.
    """
    resolved = set(endpoints)
    for host, port in endpoints:
        if not is_local(host):
            continue
        try:
            infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except OSError:
            continue
        resolved.update((str(info[4][0]).lower(), port) for info in infos)
    return frozenset(resolved)


class NetworkGuard:
    """Refuses non-local connections and lookups while installed.

    invariant: ``attempts`` lists every refused call in order, as
        ``{"call", "host", "port"}`` (a ``spawn`` names the program in
        ``host``); nothing else is recorded.
    """

    def __init__(self, proxies: frozenset[tuple[str, int]] | None = None) -> None:
        self.attempts: list[dict[str, Any]] = []
        found = proxy_endpoints() if proxies is None else proxies
        self._proxies = with_resolved(found)
        self._saved: dict[str, Any] = {}

    def refuses(self, host: Any, port: Any) -> bool:
        """True when a connection to ``(host, port)`` reaches the network."""
        if not is_local(host):
            return True
        name = host.decode() if isinstance(host, bytes) else str(host)
        return (name.lower(), port) in self._proxies

    def _refuse(self, call: str, host: Any, port: Any) -> OSError:
        name = host.decode() if isinstance(host, bytes) else host
        self.attempts.append({"call": call, "host": name, "port": port})
        return OSError(errno.ENETUNREACH, _REFUSAL)

    def _wrap_connect(self, name: str, original: Any) -> Any:
        guard = self

        def guarded(sock: socket.socket, address: Any) -> Any:
            if sock.family in (socket.AF_INET, socket.AF_INET6):
                host, port = address[0], address[1]
                if guard.refuses(host, port):
                    refusal = guard._refuse(name, host, port)
                    if name == "connect_ex":  # it reports, it does not raise
                        return refusal.errno
                    raise refusal
            return original(sock, address)

        return guarded

    def _wrap_getaddrinfo(self, original: Any) -> Any:
        guard = self

        def guarded(host: Any, port: Any, *args: Any, **kwargs: Any) -> Any:
            if not is_local(host):
                raise guard._refuse("getaddrinfo", host, port)
            return original(host, port, *args, **kwargs)

        return guarded

    def _wrap_popen_init(self, original: Any) -> Any:
        guard = self

        def guarded(popen: Any, args: Any, *rest: Any, **kwargs: Any) -> None:
            first = args if isinstance(args, (str, bytes, os.PathLike)) else args[0]
            program = os.path.basename(os.fsdecode(first).split(" ", 1)[0])
            guard.attempts.append({"call": "spawn", "host": program, "port": None})
            raise PermissionError(errno.EPERM, _REFUSAL)

        return guarded

    def install(self) -> None:
        """Patch ``socket`` and ``subprocess.Popen``. precondition: not installed."""
        if self._saved:
            raise RuntimeError("NetworkGuard is already installed")
        self._saved = {
            "connect": socket.socket.connect,
            "connect_ex": socket.socket.connect_ex,
            "getaddrinfo": socket.getaddrinfo,
            "popen_init": subprocess.Popen.__init__,
        }
        subprocess.Popen.__init__ = self._wrap_popen_init(self._saved["popen_init"])  # type: ignore[method-assign]
        socket.socket.connect = self._wrap_connect("connect", self._saved["connect"])  # type: ignore[method-assign]
        socket.socket.connect_ex = self._wrap_connect(  # type: ignore[method-assign]
            "connect_ex", self._saved["connect_ex"]
        )
        socket.getaddrinfo = self._wrap_getaddrinfo(self._saved["getaddrinfo"])

    def uninstall(self) -> None:
        """Restore the ``socket`` module as ``install`` found it."""
        if not self._saved:
            return
        socket.socket.connect = self._saved["connect"]  # type: ignore[method-assign]
        socket.socket.connect_ex = self._saved["connect_ex"]  # type: ignore[method-assign]
        socket.getaddrinfo = self._saved["getaddrinfo"]
        subprocess.Popen.__init__ = self._saved["popen_init"]  # type: ignore[method-assign]
        self._saved = {}

    def __enter__(self) -> NetworkGuard:
        self.install()
        return self

    def __exit__(self, *exc: object) -> None:
        self.uninstall()
