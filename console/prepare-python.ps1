# prepare-python.ps1 — prepara console/python-embedded, l'interprete che
# l'installer impacchetta come "python" in resources.
#
# Da eseguire UNA VOLTA prima di `npm run dist`. La cartella pesa ~220 MB ed
# e' in .gitignore: si rigenera, non si versiona.
#
#   powershell -ExecutionPolicy Bypass -File console\prepare-python.ps1
#
# Nota per chi builda su Windows: `npm install` fallisce su better-sqlite3
# (modulo nativo senza prebuilt per Node recenti, e node-gyp vuole Visual
# Studio). La via giusta e' NON compilare per Node ma per Electron:
#   npm install --ignore-scripts
#   npx electron-builder install-app-deps
# che scarica il binario gia' compilato per la ABI di Electron.

$ErrorActionPreference = "Stop"
# MAI il site-packages utente (%APPDATA%\Python\PythonXY): con "import site"
# attivo l'embeddable lo vede, pip considera le dipendenze gia' soddisfatte
# e non le installa qui — e l'installer parte senza. Trovato dallo smoke
# test dell'app impacchettata su un profilo vergine.
$env:PYTHONNOUSERSITE = "1"

$VER = "3.12.9"
$OUT = Join-Path $PSScriptRoot "python-embedded"
$URL = "https://www.python.org/ftp/python/$VER/python-$VER-embed-amd64.zip"

if (Test-Path (Join-Path $OUT "python.exe")) {
    Write-Host "[1/4] python embedded gia' presente, salto il download"
} else {
    Write-Host "[1/4] download Python $VER embeddable..."
    New-Item -ItemType Directory -Force -Path $OUT | Out-Null
    $zip = Join-Path $OUT "py.zip"
    Invoke-WebRequest -Uri $URL -OutFile $zip
    Expand-Archive -Path $zip -DestinationPath $OUT -Force
    Remove-Item $zip
}

# Senza 'import site' l'interprete embeddable non guarda in site-packages:
# pip installerebbe pacchetti che poi nessuno riesce a importare.
$pth = Get-ChildItem $OUT -Filter "python3*._pth" | Select-Object -First 1
if (-not $pth) { throw "._pth non trovato in $OUT" }
$c = Get-Content $pth.FullName
if ($c -match '^#import site') {
    ($c -replace '^#import site', 'import site') | Set-Content $pth.FullName -Encoding ascii
    Write-Host "[2/4] abilitato 'import site' in $($pth.Name)"
} else {
    Write-Host "[2/4] 'import site' gia' abilitato"
}

if (Test-Path (Join-Path $OUT "Scripts\pip.exe")) {
    Write-Host "[3/4] pip gia' presente"
} else {
    Write-Host "[3/4] installazione pip..."
    $gp = Join-Path $OUT "get-pip.py"
    Invoke-WebRequest -Uri "https://bootstrap.pypa.io/get-pip.py" -OutFile $gp
    & (Join-Path $OUT "python.exe") $gp --no-warn-script-location --quiet
    Remove-Item $gp
}

# Dal sorgente del repo, non da PyPI: l'installer deve portare il codice e
# le dipendenze DI QUESTO commit (una dipendenza nuova in pyproject deve
# esserci), e i metadati di versione devono coincidere con pyproject.toml.
$REPO = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
# Il Python embeddable isola sys.path (._pth): l'ambiente di build che pip
# creerebbe non e' visibile e hatchling "non si importa". Quindi hatchling
# installato a mano e --no-build-isolation.
Write-Host "[4/4] installazione gigamail[all] da $REPO ..."
& (Join-Path $OUT "python.exe") -m pip install hatchling --no-warn-script-location --quiet
if ($LASTEXITCODE -ne 0) { throw "pip install hatchling fallito (exit $LASTEXITCODE)" }
& (Join-Path $OUT "python.exe") -m pip install --no-build-isolation "$REPO[all]" --no-warn-script-location --quiet
if ($LASTEXITCODE -ne 0) { throw "pip install fallito (exit $LASTEXITCODE)" }

& (Join-Path $OUT "python.exe") -c "import ade_mail_agent, fastapi, uvicorn, mcp; import importlib.metadata as m; print('  gigamail', m.version('gigamail'), '| mcp', m.version('mcp'), '| import OK')"
Write-Host 'Pronto: ora "npm run dist"'
