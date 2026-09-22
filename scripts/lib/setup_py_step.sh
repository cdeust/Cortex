#!/usr/bin/env bash
# Library: run scripts/setup.py from install-plugin.sh and, when it fails,
# name the check that actually failed.
#
# Issue #621: the postInstall ended with "PostgreSQL must be installed and
# running first" whatever setup.py had reported — including a run whose
# four PostgreSQL checks all passed and whose only failing row was
# sentence-transformers. setup.py's verification block prints one
# "[FAIL] <check>" line per failed row, so the run's own output already
# carries the answer; it was simply thrown away.
#
# Function-only — sourcing this file runs nothing by itself.
#
# source: issue #621

# SETUP_PY_FAILURE is this library's output: the sourcing script reads it,
# so shellcheck cannot see the use from here.
# shellcheck disable=SC2034

# setup_py_failed_checks <log_file>
# Pre:  log_file holds the combined stdout/stderr of a scripts/setup.py run.
# Post: prints, on one line, the comma-separated names of every
#       "[FAIL] <name>" row in the log, ANSI colour codes stripped, minus
#       setup.py's own "Some checks failed" summary line (which names
#       nothing). Prints nothing when the log carries no such row.
setup_py_failed_checks() {
    local esc
    esc=$(printf '\033')
    sed -e "s/${esc}\[[0-9;]*m//g" "$1" 2>/dev/null | awk '
        /\[FAIL\]/ {
            sub(/^.*\[FAIL\][[:space:]]*/, "")
            if (index($0, "Some checks failed") == 1) next
            printf "%s%s", (n++ ? ", " : ""), $0
        }
    '
}

# run_setup_py <command...>
# Pre:  caller has `set -o pipefail` (install-plugin.sh does) so a failing
#       setup.py is not masked by tee's exit status.
# Post: runs the command with its output shown live AND captured; returns
#       0 on success, 1 otherwise. Sets SETUP_PY_FAILURE to a sentence
#       naming the failed checks, or — when the run died before printing
#       any — to a sentence that says so rather than blaming a component.
run_setup_py() {
    local log status failed
    log="$(mktemp)"
    SETUP_PY_FAILURE=""

    if "$@" 2>&1 | tee "$log"; then
        status=0
    else
        status=1
        failed="$(setup_py_failed_checks "$log")"
        if [ -n "$failed" ]; then
            SETUP_PY_FAILURE="Failed check(s): ${failed}."
        else
            SETUP_PY_FAILURE="It exited before reporting any check — the output above carries the cause."
        fi
    fi

    rm -f "$log"
    return "$status"
}
