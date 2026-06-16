#!/usr/bin/env bash
# run_mockfail.sh — always fails (exit 1) to test graceful degradation in Phase 3.
set -uo pipefail
echo "[mockfail] simulated failure" >&2
exit 1
