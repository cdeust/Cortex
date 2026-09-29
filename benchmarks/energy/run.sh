#!/bin/zsh
# One privileged sensor; Python validation and inference remain unprivileged.
set -euo pipefail
unsetopt BG_NICE

SCRIPT_DIR=${0:A:h}
REPO_DIR=${SCRIPT_DIR:h:h}
BENCH_PY=${ENERGY_PYTHON:-${REPO_DIR}/.venv/bin/python}
# Which unprivileged entry runs under the sensor: the embedding workload
# (default) or run_external_energy.py, which times a benchmark from the phase
# timeline it writes. source: Cortex benchmark refresh plan (2026-09-30), item (e).
ENERGY_ENTRY=${ENERGY_ENTRY:-run_embedding_energy.py}
case ${ENERGY_ENTRY} in
  run_embedding_energy.py|run_external_energy.py) ;;
  *)
    print -u2 "Unknown ENERGY_ENTRY: ${ENERGY_ENTRY}"
    exit 2
    ;;
esac
ENERGY_POWER_FILE=""
ENERGY_METER_PID=""

if [[ ! -x ${BENCH_PY} ]]; then
  print -u2 "Missing benchmark interpreter: ${BENCH_PY}"
  exit 2
fi
for ENERGY_ARG in "$@"; do
  if [[ ${ENERGY_ARG} == --help || ${ENERGY_ARG} == -h ]]; then
    exec "${BENCH_PY}" "${SCRIPT_DIR}/${ENERGY_ENTRY}" --help
  fi
done
# Required carbon flags and every numeric argument are checked before sudo.
ENERGY_SAMPLE_RATE_MS=$("${BENCH_PY}" "${SCRIPT_DIR}/${ENERGY_ENTRY}" "$@" --validate-only)
for ENERGY_ARG in "$@"; do
  if [[ ${ENERGY_ARG} == --validate-only ]]; then
    print "${ENERGY_SAMPLE_RATE_MS}"
    exit 0
  fi
  if [[ ${ENERGY_ARG} == --external-power-file* ]]; then
    print -u2 "Use ${ENERGY_ENTRY} directly for --external-power-file."
    exit 2
  fi
done
if [[ ! -t 0 ]]; then
  print -u2 "Run from an interactive terminal so macOS can read the sudo password."
  exit 2
fi

stop_meter() {
  if [[ -z ${ENERGY_METER_PID} ]]; then
    return
  fi
  if kill -0 "${ENERGY_METER_PID}" 2>/dev/null; then
    # source: ADR-0821
    #
    if ! kill -INT "${ENERGY_METER_PID}"; then
      print -u2 "Failed to stop sensor ${ENERGY_METER_PID}; refusing to wait indefinitely."
      return 1
    fi
  fi
  local ENERGY_WAIT_STATUS=0
  wait "${ENERGY_METER_PID}" || ENERGY_WAIT_STATUS=$?
  # source: ADR-0821
  #
  if (( ENERGY_WAIT_STATUS != 0 && ENERGY_WAIT_STATUS != 130 )); then
    print -u2 "Sensor exited with status ${ENERGY_WAIT_STATUS}."
    return ${ENERGY_WAIT_STATUS}
  fi
  ENERGY_METER_PID=""
}

cleanup() {
  local ENERGY_EXIT_STATUS=$?
  trap - EXIT INT TERM
  stop_meter || ENERGY_EXIT_STATUS=$?
  if [[ -n ${ENERGY_POWER_FILE} ]]; then
    if (( ENERGY_EXIT_STATUS == 0 )); then
      rm -f "${ENERGY_POWER_FILE}"
    else
      print -u2 "Raw sensor output preserved at ${ENERGY_POWER_FILE}."
    fi
  fi
  exit ${ENERGY_EXIT_STATUS}
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

print "Authorizing the macOS energy sensor (Cortex remains non-root)..."
sudo -v
ENERGY_POWER_FILE=$(mktemp /private/tmp/cortex-energy.XXXXXX.txt)
# source: ADR-0821
#
sudo -n /usr/bin/powermetrics \
  --samplers cpu_power,gpu_power,ane_power \
  --sample-rate "${ENERGY_SAMPLE_RATE_MS}" --sample-count 0 --buffer-size 1 \
  --output-file "${ENERGY_POWER_FILE}" &
ENERGY_METER_PID=$!

"${BENCH_PY}" "${SCRIPT_DIR}/${ENERGY_ENTRY}" "$@" \
  --external-power-file "${ENERGY_POWER_FILE}"
stop_meter
print "Energy benchmark complete; raw samples are in the result directory."
