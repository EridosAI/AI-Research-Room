#!/usr/bin/env bash
# One Grok converse turn via Grok Build, on the SuperGrok Heavy plan. Single reply, not an agent loop.
# Auth: uses ~/.grok/auth.json from `grok login` (subscription), NOT an API key. Keep XAI_API_KEY UNSET.
set -uo pipefail
prompt_file="${1:?usage: run_grok_converse.sh <prompt_file> <output_file>}"
output_file="${2:?}"
model="${FUSION_GROK_MODEL:-}"   # empty = grok-build-0.1 (subscription-safe)
command -v grok >/dev/null 2>&1 || { echo "[grok-converse] grok CLI missing — skip." >&2; exit 127; }
[ -n "${XAI_API_KEY:-}" ] && echo "[grok-converse] WARNING: XAI_API_KEY set — grok may bill API, not your sub. Unset it." >&2
scratch="$(mktemp -d "${TMPDIR:-/tmp}/room-grok.XXXXXX")"; trap 'rm -rf "$scratch"' EXIT
model_args=(); [ -n "$model" ] && model_args=(--model "$model")
# --cwd scratch = throwaway blast radius; --no-auto-update = no mid-run phone-home; --always-approve = no stall.
# Verify flags against your installed Grok Build (early beta).
grok -p "$(cat "$prompt_file")" --cwd "$scratch" --no-auto-update --always-approve "${model_args[@]}" \
  > "$output_file" 2> "$scratch/err.log"
[ $? -eq 0 ] && [ -s "$output_file" ] || { echo "[grok-converse] failed:" >&2; tail -20 "$scratch/err.log" >&2; exit 1; }
echo "[grok-converse] ok -> $output_file"
