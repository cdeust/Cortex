"""Child of ``test_launcher_command``: writes one line to an inherited fd.

Run as ``python scripts/launcher.py tests_py.hooks.fd_probe_child --fd N``
to prove the launcher keeps a descriptor the parent passed with ``pass_fds``
(the resident capture worker's listener and lease, issue #667).
"""

from __future__ import annotations

import os
import sys

# source: the child is invoked as ``<module> --fd <N>`` (argv[1], argv[2]).
_ARGC = 3


def main() -> None:
    if len(sys.argv) != _ARGC or sys.argv[1] != "--fd":
        raise SystemExit("usage: fd_probe_child --fd N")
    os.write(int(sys.argv[2]), b"carried")


if __name__ == "__main__":
    main()
