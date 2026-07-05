#!/usr/bin/env bash
# install-service.sh — install Fusion as an always-up systemd *system* service.
#
# Renders tools/fusion.service.template → /etc/systemd/system/fusion.service (needs sudo),
# reloads systemd, enables + (re)starts the unit, then health-checks 127.0.0.1:<port>.
# Idempotent: re-run to pick up a template change (it re-renders, reloads, and restarts).
#
# Usage:
#   tools/install-service.sh                  # user=$USER, repo=this checkout, port=8765
#   tools/install-service.sh --user alice     # run the service as a different account
#   tools/install-service.sh --repo /path     # override the repo root (default: derived)
#   tools/install-service.sh --port 8765      # health-check + service port
#
# Pairs with tools/uninstall-service.sh (disable + remove) and tools/windows-autostart.md
# (boot the WSL distro at Windows logon so systemd starts this unit).
set -euo pipefail

SELF="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$SELF/.." && pwd)"
SVC_USER="${USER:-$(id -un)}"
PORT="${RESEARCH_ROOM_PORT:-8765}"
UNIT=/etc/systemd/system/fusion.service
TEMPLATE="$SELF/fusion.service.template"

usage() { sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'; }
while [ $# -gt 0 ]; do
  case "$1" in
    --user) SVC_USER="$2"; shift 2 ;;
    --repo) REPO="$(cd "$2" && pwd)"; shift 2 ;;
    --port) PORT="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown arg: $1  (try --help)" >&2; exit 2 ;;
  esac
done

die() { echo "error: $*" >&2; exit 1; }

# --- preflight ---------------------------------------------------------------
[ -d /run/systemd/system ] || die "systemd is not running as init. Enable it in /etc/wsl.conf:
    [boot]
    systemd=true
  then 'wsl.exe --shutdown' (from Windows) and reopen the distro."
[ -f "$TEMPLATE" ] || die "template not found: $TEMPLATE"
id -u "$SVC_USER" >/dev/null 2>&1 || die "no such user: $SVC_USER"

PY="$REPO/.venv/bin/python"
[ -x "$PY" ] || die "interpreter not found: $PY
  create the venv first:  python3 -m venv .venv && .venv/bin/pip install -e ."
if ! ( cd "$REPO" && "$PY" -c "import web.server" ) >/dev/null 2>&1; then
  echo "warning: '$PY -c \"import web.server\"' failed in $REPO." >&2
  echo "         the service may crash-loop — run '.venv/bin/pip install -e .' if deps are missing." >&2
fi

# The mount the repo lives on — what RequiresMountsFor actually needs (space-safe, unlike $REPO).
MOUNT="$(findmnt -no TARGET --target "$REPO" 2>/dev/null || true)"
[ -n "$MOUNT" ] || MOUNT="$(df --output=target "$REPO" 2>/dev/null | tail -n1 || true)"
[ -n "$MOUNT" ] || MOUNT="/"

SUDO=""; [ "$(id -u)" -ne 0 ] && SUDO="sudo"

# --- render ------------------------------------------------------------------
render() {
  # '#' delimiter: paths contain '/', none contain '#'. Replacement text may contain spaces.
  sed -e "s#{{REPO}}#${REPO}#g" -e "s#{{USER}}#${SVC_USER}#g" \
      -e "s#{{MOUNT}}#${MOUNT}#g" -e "s#{{PORT}}#${PORT}#g" "$TEMPLATE"
}

tmpd="$(mktemp -d)"; trap 'rm -rf "$tmpd"' EXIT
tmp="$tmpd/fusion.service"
render > "$tmp"

echo "repo   : $REPO"
echo "user   : $SVC_USER"
echo "mount  : $MOUNT"
echo "port   : $PORT"
echo "unit   : $UNIT"
echo

if command -v systemd-analyze >/dev/null 2>&1; then
  systemd-analyze verify "$tmp" 2>&1 | sed 's/^/  verify: /' || true   # advisory (also checks the binary exists)
fi

# --- install + (re)start -----------------------------------------------------
$SUDO install -m 644 -o root -g root "$tmp" "$UNIT"
$SUDO systemctl daemon-reload
$SUDO systemctl enable fusion >/dev/null
$SUDO systemctl restart fusion        # restart (not just --now): picks up a changed unit on re-run

# --- health check ------------------------------------------------------------
echo "waiting for http://127.0.0.1:${PORT} …"
ok=0
for _ in $(seq 1 20); do
  if curl -fsS -o /dev/null "http://127.0.0.1:${PORT}/rooms" 2>/dev/null; then ok=1; break; fi
  sleep 0.5
done

active=1; systemctl is-active --quiet fusion || active=0   # port answering ≠ our unit (Room.bat may hold :PORT)

echo
if [ "$ok" -eq 1 ] && [ "$active" -eq 1 ]; then
  echo "✓ fusion is up  → http://127.0.0.1:${PORT}   (systemctl status fusion)"
  echo "  next: tools/windows-autostart.md — boot the distro at Windows logon so this starts on reboot."
elif [ "$active" -eq 0 ] && [ "$ok" -eq 1 ]; then
  echo "✗ :${PORT} answers but the fusion unit is NOT active — something else holds the port" >&2
  echo "  (a manual 'Room.bat' / 'python -m web.server' on :${PORT}? stop it, then re-run — they can't share a port)" >&2
  $SUDO systemctl --no-pager --full status fusion || true
  exit 1
else
  echo "✗ fusion did not answer on :${PORT} within ~10s" >&2
  echo "  logs: journalctl -u fusion -n 50 --no-pager" >&2
  $SUDO systemctl --no-pager --full status fusion || true
  exit 1
fi
