#!/usr/bin/env bash
# run_mockslow.sh — like run_mock.sh but sleeps first, to simulate a long-running
# round. Used by the multi-room concurrency test: a slow research round in one
# room must not block work in another. Delay overridable via RR_MOCK_DELAY (secs).
set -uo pipefail
prompt_file="${1:?usage: run_mockslow.sh <prompt_file> <output_file> [effort]}"
output_file="${2:?}"
sleep "${RR_MOCK_DELAY:-2}"
{ echo "MOCK SLOW ANSWER (deterministic)"; printf 'echo: %s\n' "$(head -c 120 "$prompt_file" | tr '\n' ' ')"; } > "$output_file"
echo "[mockslow] ok -> $output_file"
