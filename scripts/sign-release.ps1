<#
.SYNOPSIS
  Firma l'installer di una Release bozza e la pubblica.

.DESCRIPTION
  Il workflow release.yml, al push del tag vX.Y.Z, crea una Release BOZZA con
  GigaMail-Setup-X.Y.Z.exe non firmato e latest.yml. Questo script, sul PC
  con il certificato Certum (SimplySign Desktop collegato):

    1. scarica exe e latest.yml dalla bozza e controlla che l'exe sia quello
       descritto da latest.yml (sha512)
    2. firma l'exe con signtool e marca temporale Certum
    3. riscrive sha512 e size in latest.yml: la firma cambia l'exe e
       electron-updater rifiuterebbe un file con un hash diverso
    4. ricarica exe e latest.yml sulla bozza e la pubblica (salvo -NoPublish)

  La pubblicazione rilancia release.yml, che pubblica il pacchetto su PyPI.

  Requisiti: gh (autenticato), signtool (Windows SDK), SimplySign Desktop
  con il login fatto: il certificato deve comparire in certmgr.msc ->
  Personale -> Certificati.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts/sign-release.ps1 -Tag v0.5.0
#>
param(
  [Parameter(Mandatory = $true)][string]$Tag,
  # Impronta SHA1 del certificato; vuota = l'unico certificato di firma
  # codice valido in CurrentUser\My.
  [string]$Thumbprint = "",
  [string]$Repo = "adecubed/gigamail",
  [string]$TimestampUrl = "http://time.certum.pl",
  # Firma e ricarica, ma lascia la Release in bozza.
  [switch]$NoPublish
)

$ErrorActionPreference = "Stop"

function Fail($msg) { Write-Host "ERRORE: $msg" -ForegroundColor Red; exit 1 }

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
  if (-not $found) { Fail "signtool.exe non trovato: installa il Windows SDK (componente 'Signing Tools')." }
  return $found.FullName
}

function Find-Certificate {
  $codeSigning = "1.3.6.1.5.5.7.3.3"
  $certs = Get-ChildItem Cert:\CurrentUser\My | Where-Object {
    $_.NotAfter -gt (Get-Date) -and ($_.EnhancedKeyUsageList.ObjectId -contains $codeSigning)
  }
  if ($Thumbprint) { $certs = $certs | Where-Object { $_.Thumbprint -eq $Thumbprint.ToUpper() } }
  $certs = @($certs)
  if ($certs.Count -eq 0) { Fail "nessun certificato di firma codice valido. SimplySign Desktop e' collegato?" }
  if ($certs.Count -gt 1) {
    $certs | ForEach-Object { Write-Host "  $($_.Thumbprint)  $($_.Subject)" }
    Fail "piu' certificati di firma codice: scegli con -Thumbprint."
  }
  return $certs[0]
}

# ── 0. Strumenti e bozza ──────────────────────────────────────────────────
if (-not (Get-Command gh -ErrorAction SilentlyContinue)) { Fail "gh non trovato." }
$signtool = Find-SignTool
$cert = Find-Certificate
Write-Host "Certificato: $($cert.Subject)  (scade $($cert.NotAfter.ToString('yyyy-MM-dd')))"

$info = gh release view $Tag --repo $Repo --json isDraft,assets | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { Fail "Release $Tag non trovata in $Repo." }
if (-not $info.isDraft) { Fail "la Release $Tag e' gia' pubblicata: si firma solo una bozza." }

$version = $Tag.TrimStart("v")
$exeName = "GigaMail-Setup-$version.exe"
if (-not ($info.assets.name -contains $exeName)) { Fail "la bozza non ha $exeName." }
if (-not ($info.assets.name -contains "latest.yml")) { Fail "la bozza non ha latest.yml." }

$work = Join-Path $env:TEMP "gigamail-sign-$version"
if (Test-Path $work) { Remove-Item $work -Recurse -Force }
New-Item -ItemType Directory $work | Out-Null
gh release download $Tag --repo $Repo -p $exeName -p latest.yml -D $work
if ($LASTEXITCODE -ne 0) { Fail "download dalla bozza non riuscito." }
$exe = Join-Path $work $exeName
$yml = Join-Path $work "latest.yml"

# ── 1. L'exe scaricato e' quello costruito dal workflow ──────────────────
$ymlText = Get-Content $yml -Raw
if ($ymlText -notmatch [regex]::Escape($exeName)) { Fail "latest.yml non parla di $exeName." }
$oldHash = Sha512Base64 $exe
$sig = Get-AuthenticodeSignature $exe
if ($sig.Status -eq "Valid") {
  Write-Host "L'exe e' gia' firmato da $($sig.SignerCertificate.Subject): salto la firma."
} else {
  if ($ymlText -notmatch [regex]::Escape($oldHash)) {
    Fail "l'exe scaricato non corrisponde allo sha512 di latest.yml: non lo firmo."
  }
  # ── 2. Firma ───────────────────────────────────────────────────────────
  Write-Host "Firmo $exeName (SimplySign potrebbe chiedere il codice dal telefono)..."
  & $signtool sign /sha1 $cert.Thumbprint /fd sha256 /tr $TimestampUrl /td sha256 `
    /d "GigaMail" /du "https://github.com/$Repo" $exe
  if ($LASTEXITCODE -ne 0) { Fail "signtool sign non riuscito." }
  & $signtool verify /pa $exe
  if ($LASTEXITCODE -ne 0) { Fail "signtool verify: firma non valida." }
}

# ── 3. latest.yml con l'hash dell'exe firmato ────────────────────────────
$newHash = Sha512Base64 $exe
$size = (Get-Item $exe).Length
$out = foreach ($line in (Get-Content $yml)) {
  if ($line -match '^(\s*)sha512:') { "$($Matches[1])sha512: $newHash" }
  elseif ($line -match '^(\s*)size:') { "$($Matches[1])size: $size" }
  elseif ($line -match '^\s*blockMapSize:') { }   # niente .blockmap: update completo
  else { $line }
}
# UTF-8 senza BOM, a capo LF: come lo scrive electron-builder.
[IO.File]::WriteAllText($yml, (($out -join "`n") + "`n"), (New-Object Text.UTF8Encoding $false))
Write-Host "latest.yml: sha512 e size aggiornati ($size byte)."

# ── 4. Ricarica e pubblica ───────────────────────────────────────────────
gh release upload $Tag --repo $Repo $exe $yml --clobber
if ($LASTEXITCODE -ne 0) { Fail "upload non riuscito: la Release resta in bozza." }
$stale = $info.assets.name | Where-Object { $_ -like "*.blockmap" }
foreach ($b in $stale) { gh release delete-asset $Tag $b --repo $Repo -y }

# Controllo finale: quello che c'e' online e' quello firmato qui.
$check = Join-Path $work "check"
New-Item -ItemType Directory $check | Out-Null
gh release download $Tag --repo $Repo -p $exeName -D $check
if ((Sha512Base64 (Join-Path $check $exeName)) -ne $newHash) { Fail "l'exe online non e' quello firmato." }
if ((Get-AuthenticodeSignature (Join-Path $check $exeName)).Status -ne "Valid") { Fail "l'exe online non risulta firmato." }
Write-Host "Online: $exeName firmato, latest.yml coerente."

if ($NoPublish) {
  Write-Host "Bozza lasciata in bozza (-NoPublish). Pubblica con: gh release edit $Tag --repo $Repo --draft=false --latest"
  exit 0
}
gh release edit $Tag --repo $Repo --draft=false --latest
if ($LASTEXITCODE -ne 0) { Fail "pubblicazione non riuscita: la Release e' firmata ma in bozza." }
Write-Host "Pubblicata: https://github.com/$Repo/releases/tag/$Tag  (PyPI parte da solo)." -ForegroundColor Green
