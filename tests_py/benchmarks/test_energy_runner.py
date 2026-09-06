"""Run the real shell lifecycle with an unprivileged, synthetic sensor.

The fake sudo accepts authorization/start, but rejects a later sudo kill as an
expired ticket would. FIFO synchronization avoids model/sensor timing assumptions.
"""

import json
from contextlib import contextmanager
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import textwrap

import pytest


RUNNER = Path(__file__).resolve().parents[2] / "benchmarks" / "energy" / "run.sh"
FAKE_SUDO = """
import json
import os
from pathlib import Path
import signal
import sys

args = sys.argv[1:]
with Path(os.environ["ENERGY_SUDO_LOG"]).open("a") as log:
    log.write(json.dumps(args) + "\\n")
if args == ["-v"]:
    sys.exit(0)
if args[:2] == ["-n", "kill"]:
    sys.exit("sudo: a password is required")
if args[:2] != ["-n", "/usr/bin/powermetrics"]:
    sys.exit("unexpected fake sudo invocation")

def stop_sensor(signum, frame):
    Path(os.environ["ENERGY_STOPPED"]).write_text("SIGINT received")
    sys.exit(0)

signal.signal(signal.SIGINT, stop_sensor)
Path(os.environ["ENERGY_SENSOR_PID"]).write_text(str(os.getpid()))
output = Path(args[args.index("--output-file") + 1])
output.write_text("synthetic raw sensor output\\n")
with Path(os.environ["ENERGY_READY"]).open("w") as ready:
    ready.write("ready")
while True:
    signal.pause()
"""
FAKE_WORKLOAD = """
import os
from pathlib import Path
import sys

if "--validate-only" in sys.argv:
    print(1)
    sys.exit(0)
with Path(os.environ["ENERGY_READY"]).open() as ready:
    assert ready.read() == "ready"
power = Path(sys.argv[sys.argv.index("--external-power-file") + 1])
Path(os.environ["ENERGY_SNAPSHOT"]).write_bytes(power.read_bytes())
sys.exit(int(os.environ["ENERGY_WORKLOAD_STATUS"]))
"""
FAKE_MKTEMP = """
import os
from pathlib import Path

path = Path(os.environ["ENERGY_RAW"])
path.touch()
print(path)
"""


def _executable(path, source):
    path.write_text(f"#!{sys.executable}\n" + textwrap.dedent(source))
    path.chmod(0o755)


def _environment(tmp_path, workload_status):
    for name, source in (
        ("sudo", FAKE_SUDO),
        ("workload", FAKE_WORKLOAD),
        ("mktemp", FAKE_MKTEMP),
    ):
        _executable(tmp_path / name, source)
    os.mkfifo(tmp_path / "ready")
    return {
        **os.environ,
        "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}",
        "ENERGY_PYTHON": str(tmp_path / "workload"),
        "ENERGY_SUDO_LOG": str(tmp_path / "sudo.log"),
        "ENERGY_STOPPED": str(tmp_path / "stopped"),
        "ENERGY_SENSOR_PID": str(tmp_path / "sensor.pid"),
        "ENERGY_READY": str(tmp_path / "ready"),
        "ENERGY_SNAPSHOT": str(tmp_path / "snapshot.txt"),
        "ENERGY_RAW": str(tmp_path / "raw.txt"),
        "ENERGY_WORKLOAD_STATUS": str(workload_status),
    }


def _remove_test_process_group(pid):
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        return  # Successful runs have already reaped the sensor and exited.


@contextmanager
def _run_shell(env):
    master, slave = os.openpty()
    args = [shutil.which("zsh"), str(RUNNER)]
    process = subprocess.Popen(
        args,
        env=env,
        stdin=slave,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        # Test-only hang protection; no benchmark timing assertion uses this limit.
        stdout, stderr = process.communicate(timeout=10)
        yield subprocess.CompletedProcess(args, process.returncode, stdout, stderr)
    finally:
        _remove_test_process_group(process.pid)
        process.wait()
        os.close(slave)
        os.close(master)


@pytest.mark.skipif(
    os.name != "posix" or shutil.which("zsh") is None,
    reason="sensor runner requires POSIX PTY and zsh",
)
@pytest.mark.parametrize("workload_status", [0, 7])
def test_runner_stops_sensor_without_reauthenticating(tmp_path, workload_status):
    with _run_shell(_environment(tmp_path, workload_status)) as result:
        assert result.returncode == workload_status, result.stderr
        assert (tmp_path / "stopped").read_text() == "SIGINT received"
        calls = [
            json.loads(line)
            for line in (tmp_path / "sudo.log").read_text().splitlines()
        ]
        assert len(calls) == 2  # Only initial authorization and sensor startup.
        assert calls[0] == ["-v"]
        assert calls[1][:2] == ["-n", "/usr/bin/powermetrics"]
        # Assert before fixture cleanup: cleanup must not hide an orphaned sensor.
        with pytest.raises(ProcessLookupError):
            os.kill(int((tmp_path / "sensor.pid").read_text()), 0)
        assert (
            tmp_path / "snapshot.txt"
        ).read_text() == "synthetic raw sensor output\n"
        if workload_status:
            assert "Raw sensor output preserved" in result.stderr
            assert (tmp_path / "raw.txt").read_bytes() == (
                tmp_path / "snapshot.txt"
            ).read_bytes()
        else:
            assert not (tmp_path / "raw.txt").exists()
