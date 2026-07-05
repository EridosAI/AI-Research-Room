# Keep Fusion warm across a Windows reboot (WSL kickstart)

The systemd unit (`tools/install-service.sh`) keeps Fusion up **while the WSL distro is
running** — it auto-restarts on crash and stays alive as long as Windows is on. But WSL2
shuts a distro down after Windows sleeps, restarts, or you run `wsl --shutdown`, and it does
**not** boot a distro on its own at logon. So one Windows-side piece is needed: a scheduled
task that *touches* the distro at logon. Booting the distro starts systemd, and systemd
starts the enabled `fusion` unit. That's the whole mechanism — the task runs a no-op
(`true`); the side effect (the distro boots) is the point.

> Using a **system** service (not `systemctl --user`) is deliberate: system units start at
> boot regardless of an interactive login, so no `loginctl enable-linger` is needed.

Fill in your distro and user (`wsl -l -q` lists distros; this repo's is `Ubuntu-24.04`):

## Option A — one-liner (Command Prompt / PowerShell, copy-paste)

```bat
schtasks /Create /TN "Fusion autostart" /SC ONLOGON /RL LIMITED /F ^
  /TR "wsl.exe -d <distro> --user <user> true"
```

- `/SC ONLOGON` — runs at your logon; `/RL LIMITED` — normal privileges (no elevation);
  `/F` — overwrite if it already exists (so re-running is idempotent).
- Remove with: `schtasks /Delete /TN "Fusion autostart" /F`.
- **Laptop note:** tasks created this way can inherit "start only on AC power". If Fusion
  doesn't come up when you're on battery, either untick that box in Task Scheduler (below) or
  use Option B, which sets the battery flags explicitly.

## Option B — battery-safe (PowerShell, sets the power flags)

```powershell
$distro = '<distro>'; $user = '<user>'
$action   = New-ScheduledTaskAction  -Execute 'wsl.exe' -Argument "-d $distro --user $user true"
$trigger  = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName 'Fusion autostart' -Action $action -Trigger $trigger `
  -Settings $settings -Force
```

## Option C — GUI (Task Scheduler)

Create Task → General: *Run only when user is logged on*. Triggers: *At log on*.
Actions: Program `wsl.exe`, arguments `-d <distro> --user <user> true`.
Conditions: untick *Start the task only if the computer is on AC power*.

## Verify

1. `wsl.exe --shutdown` (from Windows) — the distro (and the service) stop.
2. Run the task's command yourself: `wsl.exe -d <distro> --user <user> true`.
3. Within ~10s, `http://127.0.0.1:8765` answers again — pinned tab reloads warm.
   (A real logon runs the same command, so this proves the reboot path.)

---

## The Grok seat is not covered by any of this (by design)

Fusion's **server** comes up fully without the Grok proxy. The **Grok seat** (via the Hermes
OAuth proxy at `127.0.0.1:8645`) is the one runtime dependency that auto-start can't honestly
fix: the proxy holds a SuperGrok **OAuth token that expires**, so a "restart the proxy" unit
would fake reliability it doesn't have — a live-but-unauthed proxy still can't answer, and the
seat would fail in a way a health check wouldn't catch. So:

- **Server:** always up (this doc + the systemd unit).
- **Grok seat:** degrades to *absent* until you relaunch the proxy by hand —
  `hermes proxy start --provider xai --host 127.0.0.1 --port 8645`. Every other model keeps
  working; the round just drops the Grok panelist (shown as *dropped (not counted)*).

A proper always-up proxy (its own unit **plus** a token-refresh story) is deferred — see
[DEFERRED.md](../DEFERRED.md) → "Deferred from the always-up service".
