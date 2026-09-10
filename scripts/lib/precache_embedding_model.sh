#!/usr/bin/env bash
# Library: pre-cache the sentence-transformers embedding model and report
# an honest [ok]/[!!] outcome derived from the pre-cache subprocess's exit
# code — never from merely reaching the end of the step.
#
# Extracted from scripts/setup.sh step 5 (issue #537) so the two outcomes
# can be driven and asserted in isolation: source this file, override
# python3 on PATH, then call precache_embedding_model_step directly.
# Function-only — sourcing this file runs nothing by itself.
#
# source: ADR-0783

# precache_embedding_model_step <project_dir> <deps_dir>
# Pre:  caller has already defined ok() and warn() (color-coded [ok]/[!!]
#       line printers) and spinner() (animates a backgrounded pid, returns
#       that pid's exit code via `wait`) — scripts/setup.sh defines all
#       three before sourcing this file.
# Post: prints exactly one [ok] or [!!] line, and on failure also prints
#       the pre-cache subprocess's captured output so the real cause does
#       not scroll past unread. Returns the pre-cache subprocess's exit
#       code (0 on success, non-zero otherwise) — this step never raises;
#       the caller decides whether that makes the run fatal.
precache_embedding_model_step() {
    local project_dir="$1"
    local deps_dir="$2"
    local cache_log
    cache_log="$(mktemp)"

    echo "  Pre-caching sentence-transformers model (one-time ~100MB download)..."
    PYTHONPATH="${project_dir}:${deps_dir}:${PYTHONPATH:-}" python3 -c "
from sentence_transformers import SentenceTransformer
model = SentenceTransformer('all-MiniLM-L6-v2')
emb = model.encode(['test'])
print(f'Model loaded: {emb.shape[1]}D embeddings')
" >"$cache_log" 2>&1 &
    local pid=$!

    local outcome=0
    if spinner "$pid"; then
        ok "Embedding model cached"
    else
        outcome=1
        warn "Model not pre-cached, will download on first use"
        sed 's/^/    /' "$cache_log"
    fi

    rm -f "$cache_log"
    return "$outcome"
}
