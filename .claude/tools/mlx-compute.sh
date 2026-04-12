#!/usr/bin/env bash
# mlx-compute.sh — Run ML experiments on Apple Silicon using MLX
#
# Usage:
#   tools/mlx-compute.sh check
#   tools/mlx-compute.sh run <script.py> [args...]
#   tools/mlx-compute.sh benchmark <script.py> [args...]
#   tools/mlx-compute.sh convert <model-path> [--quantize <bits>]
#   tools/mlx-compute.sh info
#
# Requires Apple Silicon (arm64) and Python mlx package.
# Exit codes: 0 success, 1 error, 2 usage error

set -euo pipefail
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
ACTION="${1:-}"
NOTEBOOK_TOOL="$REPO_ROOT/tools/lab-notebook-manager.sh"
SESSION_FILE="$REPO_ROOT/research/.session.json"
ENV_FILE="$REPO_ROOT/.env.mlx"

[[ -z "$ACTION" ]] && { echo "usage: $0 <check|run|benchmark|convert|info> [args]" >&2; exit 2; }

log_to_notebook() {
  local entry="$1"
  if [[ -f "$SESSION_FILE" && -x "$NOTEBOOK_TOOL" ]]; then
    "$NOTEBOOK_TOOL" add "$entry" --tag "mlx" 2>/dev/null || true
  fi
}

require_arm64() {
  local arch
  arch="$(uname -m)"
  if [[ "$arch" != "arm64" ]]; then
    echo "error: Apple Silicon required (detected: $arch)." >&2
    exit 1
  fi
}

require_mlx() {
  if ! python3 -c "import mlx" 2>/dev/null; then
    echo "error: mlx Python package not found. Install with: pip install mlx" >&2
    exit 1
  fi
}

load_env() {
  if [[ -f "$ENV_FILE" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    set +a
  fi
}

get_memory_gb() {
  sysctl -n hw.memsize 2>/dev/null | awk '{printf "%.0f", $1 / 1073741824}'
}

get_chip_name() {
  sysctl -n machdep.cpu.brand_string 2>/dev/null || echo "Unknown"
}

get_mlx_version() {
  python3 -c "import mlx; print(mlx.__version__)" 2>/dev/null || echo "unknown"
}

case "$ACTION" in
  check)
    echo "=== MLX Environment Check ==="
    echo ""

    # Architecture
    arch="$(uname -m)"
    if [[ "$arch" == "arm64" ]]; then
      echo "Architecture: $arch (Apple Silicon) — OK"
    else
      echo "Architecture: $arch — NOT Apple Silicon"
      exit 1
    fi

    # Chip
    chip="$(get_chip_name)"
    echo "Chip: $chip"

    # Memory
    mem="$(get_memory_gb)"
    echo "Unified Memory: ${mem} GB"

    # Python
    py_version="$(python3 --version 2>/dev/null || echo 'not found')"
    echo "Python: $py_version"

    # MLX
    if python3 -c "import mlx" 2>/dev/null; then
      mlx_ver="$(get_mlx_version)"
      echo "MLX: $mlx_ver — OK"
    else
      echo "MLX: not installed"
      echo "  Install with: pip install mlx"
      exit 1
    fi

    # MLX-LM (optional)
    if python3 -c "import mlx_lm" 2>/dev/null; then
      mlx_lm_ver="$(python3 -c 'import mlx_lm; print(mlx_lm.__version__)' 2>/dev/null || echo 'installed')"
      echo "MLX-LM: $mlx_lm_ver"
    else
      echo "MLX-LM: not installed (optional — pip install mlx-lm)"
    fi

    # Env file
    if [[ -f "$ENV_FILE" ]]; then
      echo "Env file: $ENV_FILE (loaded)"
    else
      echo "Env file: none (.env.mlx not found)"
    fi

    echo ""
    echo "MLX environment ready." ;;

  run)
    require_arm64
    require_mlx
    shift
    SCRIPT="${1:-}"
    [[ -z "$SCRIPT" ]] && { echo "usage: $0 run <script.py> [args...]" >&2; exit 2; }
    [[ ! -f "$SCRIPT" ]] && { echo "error: script not found: $SCRIPT" >&2; exit 1; }
    shift

    load_env

    echo "Running: python3 $SCRIPT $*"
    log_to_notebook "MLX run started: $SCRIPT $*"

    python3 "$SCRIPT" "$@"

    log_to_notebook "MLX run completed: $SCRIPT" ;;

  benchmark)
    require_arm64
    require_mlx
    shift
    SCRIPT="${1:-}"
    [[ -z "$SCRIPT" ]] && { echo "usage: $0 benchmark <script.py> [args...]" >&2; exit 2; }
    [[ ! -f "$SCRIPT" ]] && { echo "error: script not found: $SCRIPT" >&2; exit 1; }
    shift

    load_env

    echo "=== MLX Benchmark ==="
    echo "Script: $SCRIPT"
    echo "Args: $*"
    echo ""

    # Capture timing and memory with /usr/bin/time
    TMPLOG="$(mktemp)"
    trap 'rm -f "$TMPLOG"' EXIT

    start_ts="$(python3 -c 'import time; print(time.time())')"

    # Run with time, capture stderr for memory stats
    /usr/bin/time -l python3 "$SCRIPT" "$@" 2>"$TMPLOG"
    exit_code=$?

    end_ts="$(python3 -c 'import time; print(time.time())')"

    # Parse results
    elapsed="$(python3 -c "print(f'{$end_ts - $start_ts:.2f}')")"

    peak_mem="unknown"
    if grep -q "maximum resident set size" "$TMPLOG" 2>/dev/null; then
      # macOS /usr/bin/time -l reports bytes
      peak_bytes="$(grep "maximum resident set size" "$TMPLOG" | awk '{print $1}')"
      peak_mem="$(python3 -c "print(f'{int($peak_bytes) / 1048576:.1f} MB')")"
    fi

    # Look for throughput markers in output (tokens/sec, samples/sec, etc.)
    throughput="not reported"

    echo ""
    echo "=== Benchmark Results ==="
    echo "Elapsed: ${elapsed}s"
    echo "Peak memory: $peak_mem"
    echo "Throughput: $throughput"
    echo "Exit code: $exit_code"

    log_to_notebook "MLX benchmark: $SCRIPT — elapsed=${elapsed}s peak_mem=$peak_mem exit=$exit_code"

    exit $exit_code ;;

  convert)
    require_arm64
    shift
    MODEL_PATH="${1:-}"
    [[ -z "$MODEL_PATH" ]] && { echo "usage: $0 convert <model-path> [--quantize <bits>]" >&2; exit 2; }
    shift

    QUANTIZE=""
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --quantize) QUANTIZE="$2"; shift 2 ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
      esac
    done

    if ! python3 -c "import mlx_lm" 2>/dev/null; then
      echo "error: mlx-lm package required for model conversion." >&2
      echo "Install with: pip install mlx-lm" >&2
      exit 1
    fi

    OUTPUT_DIR="${MODEL_PATH}-mlx"
    if [[ -n "$QUANTIZE" ]]; then
      OUTPUT_DIR="${MODEL_PATH}-mlx-q${QUANTIZE}"
    fi

    echo "Converting model: $MODEL_PATH"
    [[ -n "$QUANTIZE" ]] && echo "Quantization: ${QUANTIZE}-bit"
    echo "Output: $OUTPUT_DIR"

    CMD="python3 -m mlx_lm.convert --hf-path $MODEL_PATH --mlx-path $OUTPUT_DIR"
    [[ -n "$QUANTIZE" ]] && CMD="$CMD --quantize --q-bits $QUANTIZE"

    eval "$CMD"

    echo "Conversion complete: $OUTPUT_DIR"
    log_to_notebook "MLX model converted: $MODEL_PATH -> $OUTPUT_DIR (quantize=$QUANTIZE)" ;;

  info)
    require_arm64
    echo "=== Apple Silicon ML Info ==="
    echo ""

    chip="$(get_chip_name)"
    echo "Chip: $chip"

    mem="$(get_memory_gb)"
    echo "Unified Memory: ${mem} GB"

    # GPU cores (approximate from chip name)
    echo "Architecture: $(uname -m)"
    echo "OS: $(sw_vers -productName 2>/dev/null || echo macOS) $(sw_vers -productVersion 2>/dev/null || echo '')"

    echo ""
    if python3 -c "import mlx" 2>/dev/null; then
      echo "MLX Version: $(get_mlx_version)"
      echo "MLX Backend: $(python3 -c "import mlx.core as mx; print(mx.default_device())" 2>/dev/null || echo 'unknown')"
    else
      echo "MLX: not installed"
    fi

    if python3 -c "import mlx_lm" 2>/dev/null; then
      echo "MLX-LM: $(python3 -c 'import mlx_lm; print(mlx_lm.__version__)' 2>/dev/null || echo 'installed')"
    fi

    # List local MLX models if any
    HF_HOME="${HF_HOME:-$HOME/.cache/huggingface}"
    if [[ -d "$HF_HOME/hub" ]]; then
      mlx_models="$(find "$HF_HOME/hub" -maxdepth 1 -name "models--*mlx*" -type d 2>/dev/null | wc -l | tr -d ' ')"
      echo ""
      echo "Cached MLX models: $mlx_models"
      if [[ "$mlx_models" -gt 0 ]]; then
        find "$HF_HOME/hub" -maxdepth 1 -name "models--*mlx*" -type d 2>/dev/null | while read -r d; do
          name="$(basename "$d" | sed 's/models--//' | tr '--' '/')"
          echo "  $name"
        done
      fi
    fi ;;

  *) echo "usage: $0 <check|run|benchmark|convert|info> [args]" >&2; exit 2 ;;
esac
