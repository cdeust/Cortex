"""Mutation run for the "Publish declared package tags" step of both Pipeline engines.

Usage: python -B -m tests_py.scripts.release_step_mutants <output-directory>

Each mutant edits the step identically in both workflows (so the parity test cannot
be what kills it); the native lifetime suite then runs against the mutated pair. A
mutant is killed when the suite fails; the report keeps each failing test with its
first assertion. A mutant whose text is not found once fails the run: a list that no
longer matches the step proves nothing. The baseline runs twice first, at the same
parallelism, so a timing window that the loaded machine misses is seen before any
kill is counted. Not collected by pytest: it is a harness, not a test.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = tuple(
    ROOT / ".github/workflows" / n for n in ("pipeline.yml", "pipeline-post-merge.yml")
)
SUITE = "tests_py.scripts.test_release_credential_lifetime"
# source: tests_py/scripts/_release_step_fixture.py; three suites at once fit this host.
WORKERS = int(os.environ.get("MUTATION_WORKERS", "3"))
IN = "            "  # inside release() and stop()
ST = "          "  # step level
AGENT = IN + 'stop "$SSH_AGENT_PID" "the signing agent" || status=1\n'
PUB = IN + 'if [[ -n $publisher ]]; then stop "-$publisher" "the publisher"'
PUB += " || status=1; fi\n"
WAIT = IN + 'for _ in $(seq 30); do kill -0 -- "$1" 2>/dev/null || return 0;'
WAIT += " sleep 0.1; done\n"
UNSET = ST + "unset SSH_KEY\n"
LEAK = (
    ST + 'printf \'K=%s\\n\' "$(printf %s "$SSH_KEY" | sed -n 2p)" >> "$GITHUB_ENV"\n'
)
SECOND = ST + '( ssh-agent -a "$AGENT_DIR/second" sleep 30 >/dev/null 2>&1 & )\n'
KNOWN = '"UserKnownHostsFile=\\"$RUNNER_TEMP/release-known-hosts\\""'
MUTANTS = [
    ("no-exec", "exec ssh-agent -a", "ssh-agent -a"),
    ("socket-in-repository", '"$agent_dir/agent"', "./release-agent.sock"),
    (
        "socket-under-runner-temp",
        "${TMPDIR:-/tmp}/release-agent.",
        "$RUNNER_TEMP/release-agent.",
    ),
    ("agent-dir-not-exported", ST + 'export AGENT_DIR="$agent_dir"\n', ""),
    ("keep-host-config", "ssh -F /dev/null ", "ssh "),
    ("no-batch-mode", " -o BatchMode=yes", ""),
    ("default-identity-files", " -o IdentityFile=none", ""),
    ("identities-only", "IdentitiesOnly=no", "IdentitiesOnly=yes"),
    ("global-known-hosts", "-o GlobalKnownHostsFile=/dev/null ", ""),
    (
        "known-hosts-unquoted",
        KNOWN,
        '"UserKnownHostsFile=$RUNNER_TEMP/release-known-hosts"',
    ),
    ("no-strict-host-check", "\n" + IN + "-o StrictHostKeyChecking=yes)", ")"),
    ("key-stays-in-environment", UNSET, ""),
    ("key-to-github-env", UNSET, LEAK + UNSET),
    ("second-agent", UNSET, UNSET + SECOND),
    ("no-exit-trap", ST + "trap release EXIT\n", ""),
    ("no-int-trap", ST + "trap 'exit 130' INT\n", ""),
    ("no-term-trap", ST + "trap 'exit 143' TERM\n", ""),
    ("int-exits-zero", "trap 'exit 130' INT", "trap 'exit 0' INT"),
    ("status-lost", IN + "status=$?\n", IN + "status=0\n"),
    ("reentrant-release", IN + "trap '' INT TERM\n", ""),
    ("agent-not-stopped", AGENT, ""),
    (
        "agent-failure-ignored",
        '"the signing agent" || status=1',
        '"the signing agent" || :',
    ),
    ("publisher-not-stopped", PUB, ""),
    ("publisher-pid-not-group", 'stop "-$publisher"', 'stop "$publisher"'),
    (
        "publisher-failure-ignored",
        '"the publisher" || status=1',
        '"the publisher" || :',
    ),
    ("publisher-before-agent", AGENT + PUB, PUB + AGENT),
    ("no-term-before-kill", IN + 'kill -TERM -- "$1" 2>/dev/null || return 0\n', ""),
    ("no-bounded-wait", WAIT, ""),
    ("grace-ten-seconds", "$(seq 30)", "$(seq 100)"),
    ("never-killed", IN + 'kill -KILL -- "$1" 2>/dev/null || :\n', ""),
    ("kill-silent", IN + 'echo "::error::$2 did not stop on SIGTERM"\n', ""),
    (
        "kill-succeeds",
        'SIGTERM"\n' + IN + "return 1\n",
        'SIGTERM"\n' + IN + "return 0\n",
    ),
    ("socket-not-removed", IN + 'rm -f -- "$SSH_AUTH_SOCK"\n', ""),
    ("directory-not-removed", IN + 'rmdir -- "$AGENT_DIR"\n', ""),
    ("exit-zero", IN + 'exit "$status"\n', IN + "exit 0\n"),
    ("no-job-control", ST + "set -m\n", ""),
    ("publisher-foreground", "python3 - <<'PY' &\n", "python3 - <<'PY'\n"),
    ("publisher-pid-lost", ST + "publisher=$!\n", ""),
    (
        "publisher-not-awaited",
        ST + 'wait "$publisher"\n' + ST + "PUBLISH\n",
        ST + "PUBLISH\n",
    ),
]


def run_suite(workflows):
    env = dict(
        os.environ, RELEASE_CREDENTIAL_WORKFLOWS=os.pathsep.join(map(str, workflows))
    )
    out = subprocess.run(
        [sys.executable, "-B", "-m", "unittest", SUITE],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=900,
    )
    failures = []
    for block in re.split(r"\n=+\n", out.stderr):
        head = re.match(r"(FAIL|ERROR): (\w+)", block)
        if head:
            lines = [
                ln
                for ln in block.splitlines()
                if re.match(r"\w*(Error|Exception)\b", ln)
            ]
            failures.append(
                {
                    "test": head.group(2),
                    "kind": head.group(1),
                    "assertion": (lines[-1] if lines else "")[:240],
                }
            )
    return out.returncode, failures


def judge(work, ident, old, new):
    texts = [path.read_text() for path in WORKFLOWS]
    if any(text.count(old) != 1 for text in texts):
        return {"mutant": ident, "status": "not-applicable"}
    directory = Path(tempfile.mkdtemp(prefix=ident + ".", dir=work))
    mutated = []
    for path, text in zip(WORKFLOWS, texts, strict=True):
        (directory / path.name).write_text(text.replace(old, new))
        mutated.append(directory / path.name)
    code, failures = run_suite(mutated)
    result = {
        "mutant": ident,
        "status": "killed" if code else "survived",
        "failures": failures,
    }
    print(json.dumps(result), flush=True)
    return result


def report(output, results):
    (output / "mutation.json").write_text(json.dumps(results, indent=2) + "\n")
    lines = [
        "| Mutant | Result | Killing tests (first assertion) |",
        "| --- | --- | --- |",
    ]
    for r in results:
        killers = "; ".join(
            f"{f['test']}: {f['assertion']}" for f in r.get("failures", [])
        )
        lines.append(f"| {r['mutant']} | {r['status']} | {killers.replace('|', '/')} |")
    (output / "mutation.md").write_text("\n".join(lines) + "\n")


def main():
    output = Path(sys.argv[1])
    output.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        baselines = list(pool.map(lambda _: run_suite(WORKFLOWS), range(2)))
        if any(code for code, _ in baselines):
            raise SystemExit("baseline fails, no kill is meaningful: %r" % baselines)
        with tempfile.TemporaryDirectory(prefix="release-mutants.") as work:
            results = list(pool.map(lambda m: judge(work, *m), MUTANTS))
    report(output, results)
    return 0 if all(r["status"] == "killed" for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
