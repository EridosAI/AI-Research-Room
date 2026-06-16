@echo off
REM One-click launcher for the Research Room (Windows + WSL).
REM Double-click to start; the console window IS the running server — close it to stop.
REM Portable: resolves its own folder, so it works wherever the repo lives.
for /f "usebackq delims=" %%i in (`wsl wslpath -u "%~dp0"`) do set "RR=%%i"
wsl bash -lc "cd '%RR%' && { [ -f .venv/bin/activate ] && . .venv/bin/activate; }; python3 -m web.server --open"
REM Multiple WSL distros? change `wsl` to `wsl -d <Distro>` on both lines above.
