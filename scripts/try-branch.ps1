# try-branch.ps1 - run a GigaMail branch from the sources on Windows,
# next to the installed app, with the same accounts and data.
#
# Checks what is there and does only what is missing: Git, Node 22, Python
# 3.12, the clone, the repo virtualenv, the console packages. Then closes
# the installed GigaMail and starts the console from the sources.
#
#   irm https://raw.githubusercontent.com/adecubed/gigamail/agent-bar/scripts/try-branch.ps1 | iex
#
# Run it again to update: it pulls the branch and reinstalls only if needed.

param(
  [string]$Branch = $(if ($env:GIGAMAIL_BRANCH) { $env:GIGAMAIL_BRANCH } else { 'agent-bar' }),
  [string]$Dir = (Join-Path $HOME 'gigamail-ui')
)

$ErrorActionPreference = 'Stop'
function Step($t) { Write-Host "`n== $t" -ForegroundColor Magenta }
function Ok($t)   { Write-Host "   ok  $t" -ForegroundColor Green }
function Fail($t) { Write-Host "`n   $t" -ForegroundColor Red; throw $t }
function Check($what) { if ($LASTEXITCODE -ne 0) { Fail "$what failed (exit $LASTEXITCODE)" } }
function RefreshPath {
  $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
              [Environment]::GetEnvironmentVariable('Path', 'User')
}
function Have($cmd) { [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }
function WingetInstall($id) {
  if (-not (Have 'winget')) { Fail "winget not found: install $id by hand, then run this again" }
  Write-Host "   installing $id ..."
  winget install --id $id -e --silent --accept-package-agreements --accept-source-agreements | Out-Host
  RefreshPath
}

# -- programs -------------------------------------------------------------
Step 'Programs'
if (-not (Have 'git')) { WingetInstall 'Git.Git' }
if (-not (Have 'git')) { Fail 'Git still not found: close and reopen PowerShell, then run this again' }
Ok (git --version)

$nodeOk = $false
if (Have 'node') {
  $v = (node --version) -replace '^v', ''
  $p = $v.Split('.')
  $nodeOk = ([int]$p[0] -gt 22) -or ([int]$p[0] -eq 22 -and [int]$p[1] -ge 12)
}
if (-not $nodeOk) { WingetInstall 'OpenJS.NodeJS.LTS' }
if (-not (Have 'node')) { Fail 'Node still not found: close and reopen PowerShell, then run this again' }
Ok ("node " + (node --version))

# "python" can be the Microsoft Store placeholder: trust only a real version
# a candidate is "exe|first argument": py -3.12 is the launcher asking for 3.12
$script:PyExe = $null; $script:PyArg = @()
function Py { & $script:PyExe @script:PyArg @args }
function FindPython {
  foreach ($c in @('py|-3.12', 'py|-3.11', 'python|')) {
    $exe, $arg = $c.Split('|')
    if (-not (Have $exe)) { continue }
    $a = @(); if ($arg) { $a = @($arg) }
    try { $out = & $exe @a --version 2>&1 | Out-String } catch { continue }
    if ($out -match 'Python 3\.(\d+)' -and [int]$Matches[1] -ge 10) {
      $script:PyExe = $exe; $script:PyArg = $a; return $true
    }
  }
  return $false
}
if (-not (FindPython)) { WingetInstall 'Python.Python.3.12'; [void](FindPython) }
if (-not $script:PyExe) { Fail 'Python 3.10+ not found: close and reopen PowerShell, then run this again' }
Ok (Py --version)

# -- code -----------------------------------------------------------------
Step "Code ($Branch in $Dir)"
if (-not (Test-Path (Join-Path $Dir '.git'))) {
  git clone https://github.com/adecubed/gigamail.git $Dir; Check 'git clone'
}
Push-Location $Dir
try {
  git fetch origin $Branch; Check 'git fetch'
  git checkout $Branch; Check 'git checkout'
  git pull --ff-only origin $Branch; Check 'git pull'
  Ok (git log --oneline -1)

  # -- backend ------------------------------------------------------------
  Step 'Backend (Python virtualenv)'
  $venvPy = Join-Path $Dir '.venv\Scripts\python.exe'
  if (-not (Test-Path $venvPy)) {
    Py -m venv .venv; Check 'python -m venv'
  }
  # reinstall only when pyproject.toml changed since the last install
  $stamp = Join-Path $Dir '.venv\.gigamail-installed'
  $hash = (Get-FileHash (Join-Path $Dir 'pyproject.toml')).Hash
  if (-not (Test-Path $stamp) -or (Get-Content $stamp) -ne $hash) {
    & $venvPy -m pip install -q --upgrade pip; Check 'pip upgrade'
    & $venvPy -m pip install -q -e ".[console,all]"; Check 'pip install'
    Set-Content $stamp $hash
  }
  Ok 'virtualenv ready'

  # -- console ------------------------------------------------------------
  Step 'Console (Electron)'
  Push-Location (Join-Path $Dir 'console')
  try {
    # npm.cmd, not npm: the .ps1 shim is blocked where scripts are not allowed
    $lock = (Get-FileHash 'package-lock.json').Hash
    $nstamp = 'node_modules\.gigamail-installed'
    if (-not (Test-Path $nstamp) -or (Get-Content $nstamp) -ne $lock) {
      npm.cmd ci --ignore-scripts; Check 'npm ci'
      npx.cmd electron-builder install-app-deps; Check 'electron-builder install-app-deps'
      Set-Content $nstamp $lock
    }
    Ok 'packages ready'

    # -- start ------------------------------------------------------------
    Step 'Start'
    $installed = Get-Process -Name 'GigaMail' -ErrorAction SilentlyContinue
    if ($installed) {
      Write-Host '   closing the installed GigaMail (accounts and data stay as they are)'
      $installed | Stop-Process -Force
      Start-Sleep -Seconds 2
    }
    Write-Host '   the console replaces the installed backend by itself on first start'
    npm.cmd start
  } finally { Pop-Location }
} finally { Pop-Location }
