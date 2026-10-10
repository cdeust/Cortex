"""Run only the explicitly installed Cortex wheel; never resolve in a hook.

Source: native Codex failure, 2026-10-02: uvx picked Intel CPython on an ARM
host and rebuilt cryptography until the event deadline. Setup is a separate
command; version validation prevents silent use of an older installed tool.
"""

from __future__ import annotations

import email.parser
import json
import os
from pathlib import Path
import subprocess
import sys


def requirement() -> tuple[str, str]:
    manifest = Path(__file__).resolve().parents[1] / ".codex-plugin/plugin.json"
    version = json.loads(manifest.read_text(encoding="utf-8"))["version"]
    return version, f"hypermnesia-mcp[postgresql,sqlite]=={version}"


def installed_python(version: str) -> Path:
    directory = subprocess.check_output(["uv", "tool", "dir"], text=True).strip()
    runtime = Path(directory) / "hypermnesia-mcp"
    metadata = list(
        runtime.glob("lib/python*/site-packages/hypermnesia_mcp-*.dist-info/METADATA")
    )
    metadata += list(
        runtime.glob("Lib/site-packages/hypermnesia_mcp-*.dist-info/METADATA")
    )
    if len(metadata) != 1:
        raise RuntimeError("Cortex runtime absent; run runtime.py setup first")
    installed = email.parser.Parser().parsestr(metadata[0].read_text(encoding="utf-8"))[
        "Version"
    ]
    if installed != version:
        raise RuntimeError(
            f"Cortex runtime {installed} differs from plugin {version}; "
            "run runtime.py setup"
        )
    python = runtime / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not python.is_file():
        raise RuntimeError(f"Cortex runtime interpreter absent: {python}")
    return python


def main() -> None:
    version, package = requirement()
    arguments = sys.argv[1:]
    if not arguments or (len(arguments) != 1 and arguments[0] != "server"):
        raise RuntimeError("usage: runtime.py setup|server [args...]|<hook-module>")
    module = sys.argv[1]
    if module == "setup":
        subprocess.run(
            [
                "uv",
                "tool",
                "install",
                "--python",
                sys.executable,
                "--no-build",
                package,
            ],
            check=True,
        )
        installed_python(version)
        return
    python = installed_python(version)
    if module == "server":
        os.execv(str(python), [str(python), "-I", "-m", "mcp_server", *arguments[1:]])
        return
    command = "from mcp_server.hooks.entry import main; main()"
    os.execv(str(python), [str(python), "-I", "-c", command, module])


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"[cortex runtime] {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
