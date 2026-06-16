# Create a pinnable Desktop shortcut that launches the Research Room.
# Portable: derives the repo root from this script's own location (tools/ -> repo).
# Targeting `cmd.exe /c Room.bat` (not the .bat directly) is what makes a script
# launcher pinnable to the taskbar.
$repo    = Split-Path -Parent $PSScriptRoot
$desktop = [Environment]::GetFolderPath('Desktop')
$ico     = Join-Path $repo 'room.ico'
$bat     = Join-Path $repo 'Room.bat'

$lnk = Join-Path $desktop 'Research Room.lnk'
$s = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk)
$s.TargetPath       = "$env:WINDIR\System32\cmd.exe"
$s.Arguments        = "/c `"$bat`""
if (Test-Path $ico) { $s.IconLocation = $ico }   # else Windows uses a default icon
$s.WorkingDirectory = $repo
$s.Description       = 'Multi-model research room'
$s.Save()
Write-Host "Created shortcut: $lnk"
Write-Host "Then: right-click it on the Desktop -> Pin to taskbar."
