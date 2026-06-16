#!/usr/bin/env bash
# run_mock.sh — deterministic mock runner (no model, no tokens). Exercises the
# whole CLI path: <prompt_file> <output_file> [effort] → clean answer to output.
set -uo pipefail
prompt_file="${1:?usage: run_mock.sh <prompt_file> <output_file> [effort]}"
output_file="${2:?}"
{ echo "MOCK ANSWER (deterministic)"; printf 'echo: %s\n' "$(head -c 120 "$prompt_file" | tr '\n' ' ')"; } > "$output_file"
echo "[mock] ok -> $output_file"
