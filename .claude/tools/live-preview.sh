#!/usr/bin/env bash
# live-preview.sh — Launch a live preview server for research documents
#
# Usage:
#   tools/live-preview.sh start <file> [--port <port>] [--open]
#   tools/live-preview.sh stop
#   tools/live-preview.sh status
#   tools/live-preview.sh open [<file>] [--port <port>]
#
# Supports Markdown (.md), LaTeX (.tex), and HTML (.html) files.
# Uses pandoc if available, falls back to Python markdown library.
# Exit codes: 0 success, 1 error, 2 usage error

set -euo pipefail
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
ACTION="${1:-}"
PID_FILE="$REPO_ROOT/.preview.pid"
PORT_FILE="$REPO_ROOT/.preview.port"
FILE_FILE="$REPO_ROOT/.preview.file"
DEFAULT_PORT=8090

[[ -z "$ACTION" ]] && { echo "usage: $0 <start|stop|status|open> [args]" >&2; exit 2; }

is_running() {
  [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null
}

get_port() {
  if [[ -f "$PORT_FILE" ]]; then
    cat "$PORT_FILE"
  else
    echo "$DEFAULT_PORT"
  fi
}

detect_type() {
  local file="$1"
  case "${file##*.}" in
    md|markdown) echo "markdown" ;;
    tex|latex)   echo "latex" ;;
    html|htm)    echo "html" ;;
    *)           echo "unknown" ;;
  esac
}

serve_markdown() {
  local src="$1"
  local port="$2"
  local dir
  dir="$(dirname "$src")"
  local base
  base="$(basename "$src")"
  local html_name="${base%.*}.html"
  local html_path="$dir/$html_name"

  # Convert markdown to HTML
  if command -v pandoc &>/dev/null; then
    pandoc "$src" \
      --standalone \
      --mathjax \
      --metadata title="Preview" \
      -o "$html_path" 2>/dev/null
  elif python3 -c "import markdown" 2>/dev/null; then
    python3 -c "
import markdown, pathlib
md = pathlib.Path('$src').read_text()
html = markdown.markdown(md, extensions=['tables', 'fenced_code', 'codehilite'])
wrapper = f'''<!DOCTYPE html>
<html><head><meta charset=\"utf-8\">
<style>body{{font-family:sans-serif;max-width:800px;margin:2em auto;padding:0 1em;line-height:1.6}}
pre{{background:#f4f4f4;padding:1em;overflow-x:auto}}code{{background:#f4f4f4;padding:2px 4px}}
table{{border-collapse:collapse}}td,th{{border:1px solid #ddd;padding:8px}}</style>
</head><body>{html}</body></html>'''
pathlib.Path('$html_path').write_text(wrapper)
" 2>/dev/null
  else
    # Raw serve — copy as-is with minimal wrapper
    cp "$src" "$html_path"
  fi

  # Start HTTP server
  cd "$dir"
  python3 -m http.server "$port" &>/dev/null &
  echo $! > "$PID_FILE"
  echo "$port" > "$PORT_FILE"
  echo "$src" > "$FILE_FILE"

  # Watch for changes and rebuild (macOS fswatch)
  if command -v fswatch &>/dev/null; then
    (
      fswatch -o "$src" | while read -r _; do
        if command -v pandoc &>/dev/null; then
          pandoc "$src" --standalone --mathjax --metadata title="Preview" -o "$html_path" 2>/dev/null
        elif python3 -c "import markdown" 2>/dev/null; then
          python3 -c "
import markdown, pathlib
md = pathlib.Path('$src').read_text()
html = markdown.markdown(md, extensions=['tables', 'fenced_code'])
wrapper = f'<!DOCTYPE html><html><head><meta charset=\"utf-8\"><style>body{{font-family:sans-serif;max-width:800px;margin:2em auto;padding:0 1em;line-height:1.6}}</style></head><body>{html}</body></html>'
pathlib.Path('$html_path').write_text(wrapper)
" 2>/dev/null
        fi
      done
    ) &>/dev/null &
    echo $! >> "$PID_FILE"
  fi

  echo "Preview: http://localhost:${port}/${html_name}"
}

serve_latex() {
  local src="$1"
  local port="$2"
  local dir
  dir="$(dirname "$src")"
  local base
  base="$(basename "$src" .tex)"

  # Check for LaTeX compiler
  local compiler=""
  if command -v xelatex &>/dev/null; then
    compiler="xelatex"
  elif command -v pdflatex &>/dev/null; then
    compiler="pdflatex"
  else
    echo "error: no LaTeX compiler found (pdflatex or xelatex required)." >&2
    exit 1
  fi

  # Initial compile
  echo "Compiling with $compiler..."
  (cd "$dir" && $compiler -interaction=nonstopmode "$src" >/dev/null 2>&1) || {
    echo "warning: LaTeX compilation had errors. Check the .log file." >&2
  }

  # Serve the directory
  cd "$dir"
  python3 -m http.server "$port" &>/dev/null &
  echo $! > "$PID_FILE"
  echo "$port" > "$PORT_FILE"
  echo "$src" > "$FILE_FILE"

  # Watch for changes and recompile
  if command -v fswatch &>/dev/null; then
    (
      fswatch -o "$src" | while read -r _; do
        (cd "$dir" && $compiler -interaction=nonstopmode "$src" >/dev/null 2>&1)
      done
    ) &>/dev/null &
    echo $! >> "$PID_FILE"
  fi

  echo "Preview: http://localhost:${port}/${base}.pdf"
}

serve_html() {
  local src="$1"
  local port="$2"
  local dir
  dir="$(dirname "$src")"
  local base
  base="$(basename "$src")"

  cd "$dir"
  python3 -m http.server "$port" &>/dev/null &
  echo $! > "$PID_FILE"
  echo "$port" > "$PORT_FILE"
  echo "$src" > "$FILE_FILE"

  echo "Preview: http://localhost:${port}/${base}"
}

case "$ACTION" in
  start)
    if is_running; then
      echo "error: preview already running (PID $(head -1 "$PID_FILE")). Stop it first with: $0 stop" >&2
      exit 1
    fi

    shift
    FILE="" ; PORT="$DEFAULT_PORT" ; DO_OPEN=false
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --port) PORT="$2"; shift 2 ;;
        --open) DO_OPEN=true; shift ;;
        *) FILE="$1"; shift ;;
      esac
    done

    [[ -z "$FILE" ]] && { echo "usage: $0 start <file> [--port <port>] [--open]" >&2; exit 2; }
    [[ ! -f "$FILE" ]] && { echo "error: file not found: $FILE" >&2; exit 1; }

    # Resolve to absolute path
    FILE="$(cd "$(dirname "$FILE")" && pwd)/$(basename "$FILE")"

    filetype="$(detect_type "$FILE")"
    case "$filetype" in
      markdown) serve_markdown "$FILE" "$PORT" ;;
      latex)    serve_latex "$FILE" "$PORT" ;;
      html)     serve_html "$FILE" "$PORT" ;;
      *)        echo "error: unsupported file type: ${FILE##*.}" >&2; exit 1 ;;
    esac

    if [[ "$DO_OPEN" == true ]]; then
      open "http://localhost:${PORT}/" 2>/dev/null || true
    fi ;;

  stop)
    if ! is_running; then
      echo "No preview server running."
      # Clean up stale files
      rm -f "$PID_FILE" "$PORT_FILE" "$FILE_FILE"
      exit 0
    fi

    echo "Stopping preview server..."
    while IFS= read -r pid; do
      kill "$pid" 2>/dev/null || true
    done < "$PID_FILE"
    rm -f "$PID_FILE" "$PORT_FILE" "$FILE_FILE"
    echo "Preview stopped." ;;

  status)
    if is_running; then
      port="$(get_port)"
      file=""
      [[ -f "$FILE_FILE" ]] && file="$(cat "$FILE_FILE")"
      pid="$(head -1 "$PID_FILE")"
      echo "Preview server is running."
      echo "  PID: $pid"
      echo "  Port: $port"
      echo "  File: $file"
      echo "  URL: http://localhost:${port}/"
    else
      echo "No preview server running."
      # Clean up stale PID file
      rm -f "$PID_FILE" "$PORT_FILE" "$FILE_FILE"
    fi ;;

  open)
    shift
    FILE="${1:-}" ; PORT="$DEFAULT_PORT"
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --port) PORT="$2"; shift 2 ;;
        *) FILE="$1"; shift ;;
      esac
    done

    if [[ -n "$FILE" ]]; then
      # Start and open
      if is_running; then
        echo "Stopping existing preview..."
        while IFS= read -r pid; do
          kill "$pid" 2>/dev/null || true
        done < "$PID_FILE"
        rm -f "$PID_FILE" "$PORT_FILE" "$FILE_FILE"
      fi

      [[ ! -f "$FILE" ]] && { echo "error: file not found: $FILE" >&2; exit 1; }
      FILE="$(cd "$(dirname "$FILE")" && pwd)/$(basename "$FILE")"

      filetype="$(detect_type "$FILE")"
      case "$filetype" in
        markdown) serve_markdown "$FILE" "$PORT" ;;
        latex)    serve_latex "$FILE" "$PORT" ;;
        html)     serve_html "$FILE" "$PORT" ;;
        *)        echo "error: unsupported file type: ${FILE##*.}" >&2; exit 1 ;;
      esac

      open "http://localhost:${PORT}/" 2>/dev/null || true
    elif is_running; then
      port="$(get_port)"
      open "http://localhost:${port}/" 2>/dev/null || true
    else
      echo "error: no preview running and no file specified." >&2
      exit 1
    fi ;;

  *) echo "usage: $0 <start|stop|status|open> [args]" >&2; exit 2 ;;
esac
