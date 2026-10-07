<#
.SYNOPSIS
  Signs a draft Release (app, uninstaller and installer) and publishes it.

.DESCRIPTION
  release.yml, on the vX.Y.Z tag push, creates a DRAFT Release with the
  unsigned GigaMail-Setup-X.Y.Z.exe, latest.yml and GigaMail-unpacked-X.Y.Z.zip
  (the app exactly as CI built and tested it). On the PC with the Certum
  certificate (SimplySign Desktop logged in), this script:

    1. downloads the unpacked app and signs GigaMail.exe
    2. packs the installer again from those files with electron-builder
       (--prepackaged): the console/sign.js hook signs the uninstaller and
       the installer, and electron-builder writes a latest.yml whose sha512
       is the signed installer's
    3. checks that all three signatures are there and valid
    4. replaces exe and latest.yml on the draft, removes the zip, checks
       what is online and publishes (unless -NoPublish)

  Publishing re-runs release.yml, which publishes the package to PyPI.

  Requirements: gh (logged in), signtool (Windows SDK), node with
  console/node_modules installed, the repository checked out at the tag,
  SimplySign Desktop logged in: the certificate must show in certmgr.msc ->
  Personal -> Certificates.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts/sign-release.ps1 -Tag v0.5.0 -NoPublish
#>
param(
  [Parameter(Mandatory = $true)][string]$Tag,
  # SHA1 thumbprint of the certificate; empty = the only valid code signing
  # certificate in CurrentUser\My.
  [string]$Thumbprint = "",
  [string]$Repo = "adecubed/gigamail",
  [string]$TimestampUrl = "http://time.certum.pl",
  # Sign and upload, but leave the Release as a draft.
  [switch]$NoPublish
)

$ErrorActionPreference = "Stop"
$it = if ($env:GIGAMAIL_LANG) { $env:GIGAMAIL_LANG -like "it*" } else { (Get-Culture).TwoLetterISOLanguageName -eq "it" }

function Say($itText, $enText) { if ($it) { $itText } else { $enText } }
function Fail($itText, $enText) { Write-Host ("ERRORE: " + (Say $itText $enText)) -ForegroundColor Red; exit 1 }

function Sha512Base64($path) {
  $sha = [Security.Cryptography.SHA512]::Create()
  $fs = [IO.File]::OpenRead($path)
  try { [Convert]::ToBase64String($sha.ComputeHash($fs)) } finally { $fs.Dispose(); $sha.Dispose() }
}

function Find-SignTool {
  $cmd = Get-Command signtool.exe -ErrorAction SilentlyContinue
  if ($cmd) { return $cmd.Source }
  $kits = Join-Path ${env:ProgramFiles(x86)} "Windows Kits\10\bin"
  $found = Get-ChildItem $kits -Recurse -Filter signtool.exe -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -match "\\x64\\" } |
    Sort-Object FullName -Descending | Select-Object -First 1
  if (-not $found) { Fail "signtool.exe non trovato: installa il Windows SDK (componente 'Signing Tools')." "signtool.exe not found: install the Windows SDK ('Signing Tools')." }
  return $found.FullName
}

function Find-Certificate {
  $codeSigning = "1.3.6.1.5.5.7.3.3"
  $certs = Get-ChildItem Cert:\CurrentUser\My | Where-Object {
    $_.NotAfter -gt (Get-Date) -and ($_.EnhancedKeyUsageList.ObjectId -contains $codeSigning)
  }
  if ($Thumbprint) { $certs = $certs | Where-Object { $_.Thumbprint -eq $Thumbprint.ToUpper() } }
  $certs = @($certs)
  if ($certs.Count -eq 0) { Fail "nessun certificato di firma codice valido. SimplySign Desktop e' collegato?" "no valid code signing certificate. Is SimplySign Desktop logged in?" }
  if ($certs.Count -gt 1) {
    $certs | ForEach-Object { Write-Host "  $($_.Thumbprint)  $($_.Subject)" }
    Fail "piu' certificati di firma codice: scegli con -Thumbprint." "several code signing certificates: pick one with -Thumbprint."
  }
  return $certs[0]
}

function Test-SignedByUs($path) {
  $s = Get-AuthenticodeSignature $path
  return $s.Status -eq "Valid" -and $s.SignerCertificate.Thumbprint -eq $cert.Thumbprint
}

# ── 0. Tools, checkout, draft ─────────────────────────────────────────────
$root = Split-Path $PSScriptRoot -Parent
$console = Join-Path $root "console"
if (-not (Get-Command gh -ErrorAction SilentlyContinue)) { Fail "gh non trovato." "gh not found." }
if (-not (Get-Command node -ErrorAction SilentlyContinue)) { Fail "node non trovato." "node not found." }
# electron-builder 26 needs require(esm): Node 22.12+, as console/package.json says.
$nodeVer = [version]((node -v).TrimStart("v"))
if ($nodeVer -lt [version]"22.12.0") {
  Fail "serve Node 22.12 o piu' recente (ora $nodeVer): 'fnm use 22' prima di lanciare lo script." "Node 22.12 or newer needed (now $nodeVer): 'fnm use 22' before running the script."
}
if (-not (Test-Path (Join-Path $console "node_modules\electron-builder"))) {
  Fail "manca console\node_modules: esegui 'npm ci --ignore-scripts' in console." "console\node_modules missing: run 'npm ci --ignore-scripts' in console."
}
$signtool = Find-SignTool
$cert = Find-Certificate
Write-Host ((Say "Certificato: " "Certificate: ") + "$($cert.Subject)  ($((Say 'scade' 'expires')) $($cert.NotAfter.ToString('yyyy-MM-dd')))")

# The installer is packed with this checkout's electron-builder config: it
# must be the commit CI built.
$head = git -C $root rev-parse HEAD
$tagCommit = git -C $root rev-parse "$Tag^{commit}" 2>$null
if (-not $tagCommit) { Fail "tag $Tag assente in locale: git fetch --tags" "tag $Tag not found locally: git fetch --tags" }
if ($head -ne $tagCommit) { Fail "il repository non e' su ${Tag}: git checkout $Tag" "the repository is not at ${Tag}: git checkout $Tag" }
if (git -C $root status --porcelain -- console) { Fail "console\ ha modifiche non committate." "console\ has uncommitted changes." }

$info = gh release view $Tag --repo $Repo --json isDraft,assets | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { Fail "Release $Tag non trovata in $Repo." "Release $Tag not found in $Repo." }
if (-not $info.isDraft) { Fail "la Release $Tag e' gia' pubblicata: si firma solo una bozza." "Release $Tag is already published: only a draft is signed." }

$version = $Tag.TrimStart("v")
$exeName = "GigaMail-Setup-$version.exe"
$zipName = "GigaMail-unpacked-$version.zip"
$names = @($info.assets.name)
if (-not ($names -contains $exeName)) { Fail "la bozza non ha $exeName." "the draft has no $exeName." }
if (-not ($names -contains "latest.yml")) { Fail "la bozza non ha latest.yml." "the draft has no latest.yml." }

$work = Join-Path $env:TEMP "gigamail-sign-$version"
if (Test-Path $work) { Remove-Item $work -Recurse -Force }
New-Item -ItemType Directory $work | Out-Null
$exe = Join-Path $work $exeName
$yml = Join-Path $work "latest.yml"

if (-not ($names -contains $zipName)) {
  # A previous run already replaced the installer and removed the zip.
  gh release download $Tag --repo $Repo -p $exeName -p latest.yml -D $work
  if ($LASTEXITCODE -ne 0) { Fail "download dalla bozza non riuscito." "download from the draft failed." }
  if (-not (Test-SignedByUs $exe)) { Fail "la bozza non ha $zipName e l'installer non e' firmato: rilancia la build del tag." "the draft has no $zipName and the installer is not signed: re-run the tag build." }
  Write-Host (Say "L'installer della bozza e' gia' firmato: passo alla pubblicazione." "The draft installer is already signed: going on to publishing.")
} else {
  # ── 1. The app CI built, with GigaMail.exe signed ──────────────────────
  gh release download $Tag --repo $Repo -p $zipName -D $work
  if ($LASTEXITCODE -ne 0) { Fail "download di $zipName non riuscito." "download of $zipName failed." }
  $unpacked = Join-Path $work "win-unpacked"
  New-Item -ItemType Directory $unpacked | Out-Null
  # Expand-Archive, not tar: from a Git Bash shell `tar` is GNU tar, which
  # does not understand C:\ paths.
  try { Expand-Archive -Path (Join-Path $work $zipName) -DestinationPath $unpacked -Force }
  catch { Fail "estrazione di $zipName non riuscita: $_" "extracting $zipName failed: $_" }
  $appExe = Join-Path $unpacked "GigaMail.exe"
  if (-not (Test-Path $appExe)) { Fail "$zipName non contiene GigaMail.exe." "$zipName has no GigaMail.exe." }

  $log = Join-Path $work "signed.txt"
  $env:GIGAMAIL_SIGN_SHA1 = $cert.Thumbprint
  $env:GIGAMAIL_SIGNTOOL = $signtool
  $env:GIGAMAIL_SIGN_TIMESTAMP = $TimestampUrl
  $env:GIGAMAIL_SIGN_LOG = $log
  try {
    Write-Host (Say "Firmo GigaMail.exe (SimplySign potrebbe chiedere il codice dal telefono)..." "Signing GigaMail.exe (SimplySign may ask for the code on the phone)...")
    node -e "require(process.argv[1])({ path: process.argv[2] })" (Join-Path $console "sign.js") $appExe
    if ($LASTEXITCODE -ne 0) { Fail "firma di GigaMail.exe non riuscita." "signing GigaMail.exe failed." }

    # ── 2. Installer packed again: the hook signs uninstaller and installer
    $out = Join-Path $work "out"
    Write-Host (Say "Impacchetto l'installer firmato..." "Packing the signed installer...")
    Push-Location $console
    try {
      node node_modules/electron-builder/cli.js --win --prepackaged $unpacked --publish never `
        "-c.extraMetadata.version=$version" "-c.directories.output=$out"
      if ($LASTEXITCODE -ne 0) { Fail "electron-builder non riuscito." "electron-builder failed." }
    } finally { Pop-Location }
  } finally {
    Remove-Item Env:GIGAMAIL_SIGN_SHA1, Env:GIGAMAIL_SIGNTOOL, Env:GIGAMAIL_SIGN_TIMESTAMP, Env:GIGAMAIL_SIGN_LOG -ErrorAction SilentlyContinue
  }

  # ── 3. Three signatures, all ours ──────────────────────────────────────
  $built = Join-Path $out "GigaMail Setup $version.exe"
  if (-not (Test-Path $built)) { Fail "installer $version non prodotto." "installer $version not produced." }
  $signed = if (Test-Path $log) { Get-Content $log } else { @() }
  if (-not ($signed -contains "GigaMail.exe")) { Fail "GigaMail.exe non risulta firmato." "GigaMail.exe is not reported as signed." }
  if (-not ($signed | Where-Object { $_ -like "*uninstall*" })) { Fail "il disinstallatore non risulta firmato." "the uninstaller is not reported as signed." }
  if (-not ($signed -contains "GigaMail Setup $version.exe")) { Fail "l'installer non risulta firmato." "the installer is not reported as signed." }
  if (-not (Test-SignedByUs $appExe)) { Fail "GigaMail.exe: firma non valida." "GigaMail.exe: invalid signature." }
  if (-not (Test-SignedByUs $built)) { Fail "installer: firma non valida." "installer: invalid signature." }

  $builtYml = Join-Path $out "latest.yml"
  $ymlText = Get-Content $builtYml -Raw
  if ($ymlText -notmatch [regex]::Escape($exeName)) { Fail "latest.yml non parla di $exeName." "latest.yml does not name $exeName." }
  if ($ymlText -notmatch [regex]::Escape((Sha512Base64 $built))) { Fail "latest.yml non ha lo sha512 dell'installer firmato." "latest.yml lacks the signed installer's sha512." }
  Copy-Item $built $exe
  # No .blockmap is uploaded: the update downloads the whole installer.
  $lines = Get-Content $builtYml | Where-Object { $_ -notmatch '^\s*blockMapSize:' }
  # UTF-8 without BOM, LF line ends: as electron-builder writes it.
  [IO.File]::WriteAllText($yml, (($lines -join "`n") + "`n"), (New-Object Text.UTF8Encoding $false))
  Write-Host (Say "Firmati: GigaMail.exe, disinstallatore, installer." "Signed: GigaMail.exe, uninstaller, installer.")

  # ── 4. Upload ───────────────────────────────────────────────────────────
  gh release upload $Tag --repo $Repo $exe $yml --clobber
  if ($LASTEXITCODE -ne 0) { Fail "upload non riuscito: la Release resta in bozza." "upload failed: the Release stays a draft." }
}

$newHash = Sha512Base64 $exe
$stale = $names | Where-Object { $_ -like "*.blockmap" -or $_ -eq $zipName }
foreach ($b in $stale) { gh release delete-asset $Tag $b --repo $Repo -y }

# Final check: what is online is what was signed here.
$check = Join-Path $work "check"
New-Item -ItemType Directory $check | Out-Null
gh release download $Tag --repo $Repo -p $exeName -D $check
if ((Sha512Base64 (Join-Path $check $exeName)) -ne $newHash) { Fail "l'exe online non e' quello firmato." "the exe online is not the signed one." }
if (-not (Test-SignedByUs (Join-Path $check $exeName))) { Fail "l'exe online non risulta firmato." "the exe online is not signed." }
Write-Host (Say "Online: $exeName firmato, latest.yml coerente." "Online: $exeName signed, latest.yml consistent.")

if ($NoPublish) {
  Write-Host (Say "Bozza lasciata in bozza (-NoPublish). Pubblica con: " "Left as a draft (-NoPublish). Publish with: ") "gh release edit $Tag --repo $Repo --draft=false --latest"
  exit 0
}
gh release edit $Tag --repo $Repo --draft=false --latest
if ($LASTEXITCODE -ne 0) { Fail "pubblicazione non riuscita: la Release e' firmata ma in bozza." "publishing failed: the Release is signed but still a draft." }
Write-Host ((Say "Pubblicata: " "Published: ") + "https://github.com/$Repo/releases/tag/$Tag  (PyPI)") -ForegroundColor Green
