"""Stand-in programs and configuration that the release step fixture installs.

SSH_WRAPPER replaces the ssh client Git runs: it records the effective client
configuration (real `ssh -G`) and the agent it was given, has that agent sign, then
serves the Git command against the local receiver. A blocked transport waits until
Git goes away, then ends as a real client does on EOF.
"""

# source: ssh_config(5); every option here would change the transport if it applied.
HOSTILE_SSH_CONFIG = """Host *
  ProxyCommand /usr/bin/false
  IdentitiesOnly yes
  IdentityFile ~/.ssh/host-identity
  BatchMode no
  StrictHostKeyChecking no
  UserKnownHostsFile /dev/null
"""

# source: git-scm.com/docs/git, GIT_SSH_COMMAND runs as: command [args] host cmd
SSH_WRAPPER = """#!/bin/sh
set -u
log="$FIXTURE_LOG/ssh.$$"
"$FIXTURE_REAL_SSH" -G "$@" > "$log.config" 2>&1
{
  echo "pid=$$"
  echo "parent=$PPID"
  echo "socket=${SSH_AUTH_SOCK-}"
  echo "agent=${SSH_AGENT_PID-}"
  echo "key_in_environment=${SSH_KEY+yes}"
  ssh-add -l >/dev/null 2>&1; echo "list=$?"
  ssh-add -T "$FIXTURE_PUBLIC_KEY" >/dev/null 2>&1; echo "signed=$?"
} > "$log.env"
[ -z "${FIXTURE_RECORD_AGENT-}" ] ||
  printf '%s' "$SSH_AGENT_PID" > "$FIXTURE_LOG/agent-pid"
: > "$log.ready"
if [ -n "${FIXTURE_BLOCK-}" ]; then
  while kill -0 "$PPID" 2>/dev/null; do sleep 0.05; done
  exit 255
fi
grep -qx signed=0 "$log.env" || exit 255
for command; do :; done
exec sh -c "$command"
"""

# source: docs.python.org/3/library/site.html, sitecustomize runs before the script.
IGNORE_TERM = "import signal\nsignal.signal(signal.SIGTERM, signal.SIG_IGN)\n"

# source: ssh-agent(1); one line per invocation, so a second agent is visible.
AGENT_WRAPPER = """#!/bin/sh
printf '%s\\n' "${1-}" >> "$FIXTURE_LOG/agent-starts"
exec "$FIXTURE_REAL_AGENT" "$@"
"""
