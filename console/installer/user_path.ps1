# user_path.ps1 - run by the installer (add) and the uninstaller (remove):
# puts the folder with GigaMail's command-line launchers on PATH, or takes
# it off.
#
# Why. MCP clients start the server by name: the Codex and Claude Code
# plugins run `gigamail-server`, and the documented one-liner is
# `codex mcp add gigamail -- gigamail-server`. On a desktop install that
# name was nowhere on PATH, so those worked only after the console had
# written this installation's full path into the client's configuration.
#
# What. The Path value is edited in the registry, never through
# [Environment]::SetEnvironmentVariable: that call reads the value with
# its %VARIABLES% expanded and writes the expanded text back, which
# freezes every entry such as %USERPROFILE%\bin. Here the raw text and its
# kind (REG_EXPAND_SZ or REG_SZ) are kept, and only our folder is added at
# the end or removed. A per-user install edits the user's Path; an "all
# users" install, which runs elevated, the machine's. Removing looks in
# both, so a leftover from the other kind of install goes too.
param(
  [Parameter(Mandatory = $true)][ValidateSet('add', 'remove')][string]$Action,
  [Parameter(Mandatory = $true)][string]$Dir,
  [string]$Mode = 'CurrentUser'
)

$ErrorActionPreference = 'Stop'
$want = $Dir.TrimEnd('\')

function Edit-Path($hive, $subkey) {
  $key = $hive.OpenSubKey($subkey, $true)
  if (-not $key) { return $false }
  try {
    $kind = [Microsoft.Win32.RegistryValueKind]::ExpandString
    $old = ''
    if ($key.GetValueNames() -contains 'Path') {
      $kind = $key.GetValueKind('Path')
      $old = [string]$key.GetValue('Path', '', [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
    }
    $parts = @($old -split ';' | Where-Object { $_ -ne '' })
    $others = @($parts | Where-Object { $_.Trim().TrimEnd('\') -ine $want })
    $present = $others.Count -ne $parts.Count
    if ($Action -eq 'add') {
      if ($present) { return $false }
      $others = $parts + $want
    } elseif (-not $present) {
      return $false
    }
    $key.SetValue('Path', ($others -join ';'), $kind)
    return $true
  } finally {
    $key.Close()
  }
}

$script:changed = $false
function Update-Scope($hive, $subkey) {
  try {
    if (Edit-Path $hive $subkey) { $script:changed = $true }
  } catch {
    # The machine's Path without administrator rights: not ours to edit.
    Write-Output "skipped ${subkey}: $($_.Exception.Message)"
  }
}

$userKey = 'Environment'
$machineKey = 'SYSTEM\CurrentControlSet\Control\Session Manager\Environment'
if ($Action -eq 'remove') {
  Update-Scope ([Microsoft.Win32.Registry]::CurrentUser) $userKey
  Update-Scope ([Microsoft.Win32.Registry]::LocalMachine) $machineKey
} elseif ($Mode -eq 'all') {
  Update-Scope ([Microsoft.Win32.Registry]::LocalMachine) $machineKey
} else {
  Update-Scope ([Microsoft.Win32.Registry]::CurrentUser) $userKey
}

if ($script:changed) {
  # Programs started from now on must see the new Path without a logoff:
  # deleting a user variable that does not exist changes nothing and makes
  # Windows broadcast WM_SETTINGCHANGE "Environment".
  [Environment]::SetEnvironmentVariable('GIGAMAIL_PATH_REFRESH', $null, 'User')
  Write-Output "$Action $want"
} else {
  Write-Output "nothing to do for $want"
}
exit 0
