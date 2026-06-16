#!/usr/bin/env bash
# run_grok.sh — run one Grok panelist/judge (via xAI's Grok Build CLI) on a prompt, web + shell.
#
# Usage: run_grok.sh <prompt_file> <output_file> [effort]
#
# Contract: clean final answer to <output_file>; exit 127 if CLI missing; exit 1 on failure.
#
# Requires Grok Build:  curl -fsSL https://x.ai/cli/install.sh | bash
# Headless auth:        export GROK_CODE_XAI_API_KEY="xai-..."
# Grok Build is agentic (edits files, runs shell, web search), so a Grok panelist has the
# same tool parity as the codex/claude panelists.
#
# -p = headless: reads the prompt, runs to completion, prints the final result to stdout.
# VERIFY the exact flags against your installed Grok Build version (the "final-message-only"
# capture is the one line most likely to differ between versions).

set -uo pipefail

prompt_file="${1:?usage: run_grok.sh <prompt_file> <output_file> [effort]}"
output_file="${2:?usage: run_grok.sh <prompt_file> <output_file> [effort]}"
effort="${3:-medium}"

command -v grok >/dev/null 2>&1 || { echo "[run_grok.sh] grok CLI not installed — skip this panelist." >&2; exit 127; }

scratch="$(mktemp -d "${TMPDIR:-/tmp}/fusion-grok.XXXXXX")"
trap 'rm -rf "$scratch"' EXIT

model_args=()
[ -n "${FUSION_GROK_MODEL:-}" ] && model_args=(--model "${FUSION_GROK_MODEL}")

# Headless run in a throwaway dir so the panelist's file writes never touch your repo.
( cd "$scratch" && grok -p "$(cat "$prompt_file")" "${model_args[@]}" ) \
    > "$output_file" 2> "$scratch/err.log"
status=$?

if [ $status -ne 0 ] || [ ! -s "$output_file" ]; then
  echo "[run_grok.sh] grok exited $status or produced no output; tail of err:" >&2
  tail -20 "$scratch/err.log" >&2
  exit 1
fi
echo "[run_grok.sh] ok -> $output_file"
