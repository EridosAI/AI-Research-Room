#!/usr/bin/env bash
# uninstall-service.sh — remove the Fusion systemd system service.
#
# Stops + disables the unit and deletes /etc/systemd/system/fusion.service, then reloads
# systemd. Tolerant of a partial/absent install (safe to run twice). Does NOT touch the
# vault, config.toml, secrets.json, or the Windows logon task — remove that in Task Scheduler.
set -euo pipefail

UNIT=/etc/systemd/system/fusion.service
SUDO=""; [ "$(id -u)" -ne 0 ] && SUDO="sudo"

$SUDO systemctl disable --now fusion 2>/dev/null || true   # stop + remove the enable symlink
$SUDO rm -f "$UNIT"
$SUDO systemctl daemon-reload

echo "✓ fusion service removed. Dev path (Room.bat / python -m web.server) is unaffected."
