# stop_backend.ps1 — run by the installer (and the uninstaller) before any
# file is replaced: ends every process still running from the install
# folder, and makes sure none comes back while the files are swapped.
#
# Why. The console leaves its backend running after the window closes,
# and the watcher is a process of its own; an update over live python.exe
# left resources\python half replaced (0.6.1). Worse, since the console
# connects ChatGPT/Codex and Claude Desktop to this very installation,
# those apps run GigaMail's MCP server from resources\python too, and
# RESTART it the instant it is killed. electron-builder's own check
# ("is anything running from the install folder?") then never came clean:
# the old uninstaller gave up, the installer wrote over a python DLL in
# use and sat forever on a hidden "error opening file for writing" box
# (0.6.5, every machine with the ChatGPT or Codex app open).
#
# What. 1) end every process whose executable lives under the install
# folder (the app, the backend, the watcher, the MCP server, their
# launchers), and whatever listens on the console port that was started
# as the GigaMail backend from any folder; 2) rename python.exe and the
# gigamail-server launcher to *.updating, so an MCP client's automatic
# restart fails until the new files are in place (Windows allows renaming
# a running executable; the old files are moved away by the uninstaller
# anyway). Any other program on the machine is left alone.
param([Parameter(Mandatory = $true)][string]$Root)

$ErrorActionPreference = 'SilentlyContinue'
$root = $Root.TrimEnd('\') + '\'
$me = $PID
$ids = @()

$here = Get-CimInstance Win32_Process |
  Where-Object { $_.ProcessId -ne $me -and $_.ExecutablePath -and $_.ExecutablePath.StartsWith($root, [System.StringComparison]::OrdinalIgnoreCase) }
foreach ($p in $here) { $ids += $p.ProcessId }

$port = 8002
if ($env:ADE_CONSOLE_PORT -match '^\d+$') { $port = [int]$env:ADE_CONSOLE_PORT }
$owners = Get-NetTCPConnection -LocalPort $port -State Listen | Select-Object -ExpandProperty OwningProcess -Unique
foreach ($owner in $owners) {
  $p = Get-CimInstance Win32_Process -Filter "ProcessId = $owner"
  if ($p -and $p.CommandLine -and $p.CommandLine -like '*gigamail.http_api*') { $ids += $p.ProcessId }
}

$ids = @($ids | Sort-Object -Unique)
foreach ($id in $ids) { Stop-Process -Id $id -Force }
if ($ids.Count) { Wait-Process -Id $ids -Timeout 15 }

# Nothing from this folder may start again until the new files are there.
foreach ($exe in @('resources\python\python.exe', 'resources\python\pythonw.exe',
                   'resources\python\Scripts\gigamail-server.exe')) {
  $path = Join-Path $root $exe
  if (Test-Path -LiteralPath $path) {
    Remove-Item -LiteralPath ($path + '.updating') -Force
    Rename-Item -LiteralPath $path -NewName ((Split-Path -Leaf $path) + '.updating') -Force
  }
}
# A restart that slipped in between the kill and the rename.
$again = Get-CimInstance Win32_Process |
  Where-Object { $_.ProcessId -ne $me -and $_.ExecutablePath -and $_.ExecutablePath.StartsWith($root, [System.StringComparison]::OrdinalIgnoreCase) }
foreach ($p in $again) { Stop-Process -Id $p.ProcessId -Force }
exit 0
