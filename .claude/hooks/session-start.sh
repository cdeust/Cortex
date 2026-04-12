#!/usr/bin/env bash
# session-start.sh — Load context at session start
set -euo pipefail
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
TOOLS="$REPO_ROOT/tools"

# --- Colors (true color RGB — readable on dark backgrounds) ---
TEAL="\033[1;38;2;127;187;179m"
WHITE="\033[38;2;224;224;224m"
LIGHT="\033[38;2;190;195;190m"
SUBTLE="\033[38;2;150;160;155m"
BOLD="\033[1m"
RESET="\033[0m"

# --- Banner ---
echo ""
echo -e "${TEAL}  ███████╗███████╗████████╗███████╗████████╗██╗ ██████╗${RESET}"
echo -e "${TEAL}  ╚══███╔╝██╔════╝╚══██╔══╝██╔════╝╚══██╔══╝██║██╔════╝${RESET}"
echo -e "${TEAL}    ███╔╝ █████╗     ██║   █████╗     ██║   ██║██║     ${RESET}"
echo -e "${TEAL}   ███╔╝  ██╔══╝     ██║   ██╔══╝     ██║   ██║██║     ${RESET}"
echo -e "${TEAL}  ███████╗███████╗   ██║   ███████╗   ██║   ██║╚██████╗${RESET}"
echo -e "${TEAL}  ╚══════╝╚══════╝   ╚═╝   ╚══════╝   ╚═╝   ╚═╝ ╚═════╝${RESET}"
echo ""
echo -e "${WHITE}${BOLD}  A G E N T S${RESET}"
echo ""
echo -e "${WHITE}  97 reasoning patterns  ·  63 skills  ·  14 hooks  ·  17 tools${RESET}"
echo ""
echo -e "${LIGHT}  Pearl ── Peirce ── Feynman ── Toulmin ── Cochrane${RESET}"
echo -e "${SUBTLE}  causal    abductive  integrity   argument   evidence${RESET}"
echo -e "${SUBTLE}  graphs    hypotheses checks      structure  synthesis${RESET}"
echo ""
echo -e "${LIGHT}  every claim cites its source · every commit is checked${RESET}"
echo -e "${LIGHT}  every agent says \"I don't know\" when it doesn't${RESET}"
echo ""
printf "%65s\n" "powered by" | sed "s/.*/${TEAL}&${RESET}/"
printf "%65s\n" "ai-architect.tools" | sed "s/.*/${TEAL}&${RESET}/"
echo ""

# --- Status ---
echo -e "${WHITE}${BOLD}  ◆ Repository${RESET}"
echo "  Branch: $(git -C "$REPO_ROOT" branch --show-current 2>/dev/null || echo 'unknown')"
echo "  Uncommitted: $(git -C "$REPO_ROOT" status --porcelain 2>/dev/null | wc -l | tr -d ' ') files"
echo "  Last commit: $(git -C "$REPO_ROOT" log --oneline -1 2>/dev/null || echo 'none')"
echo ""

echo -e "${WHITE}${BOLD}  ◆ Difficulty Books${RESET}"
"$TOOLS/difficulty-book-manager.sh" status 2>/dev/null || echo "  (none)"
echo ""

echo -e "${WHITE}${BOLD}  ◆ Agent Worktrees${RESET}"
"$TOOLS/worktree-manager.sh" list 2>/dev/null || echo "  (none)"
echo ""

echo -e "${WHITE}${BOLD}  ◆ Session Cache${RESET}"
"$TOOLS/session-store.sh" load 2>/dev/null || echo "  (no cached session)"
echo ""

echo -e "${LIGHT}  Reminder: call query_methodology for cognitive profile, recall for Cortex context.${RESET}"
