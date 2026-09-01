# GigaMail - mail for your AI agent
# Copyright (C) 2026 Adecubed
# Licensed under the GNU AGPL v3 or later. See LICENSE.
#
# Avvio del watcher da Utilita' di pianificazione.
#
# Gira NELLA SESSIONE dell'utente, mai come SYSTEM: le password degli
# account sono cifrate con DPAPI per-utente e le toast di approvazione
# esistono solo dentro una sessione interattiva. Un watcher come servizio
# non saprebbe leggere la posta e non avrebbe nessuno a cui mostrarla.

$ErrorActionPreference = 'Stop'

# La cartella dati va dichiarata, non dedotta: app_root() ripiega su
# APPDATA, e un ambiente che lo filtra farebbe nascere un SECONDO
# database di approvazioni, vuoto e silenzioso, accanto a quello vero.
if (-not $env:GIGAMAIL_ROOT) {
    $env:GIGAMAIL_ROOT = Join-Path $env:APPDATA 'ADE'
}

$log = Join-Path $env:GIGAMAIL_ROOT 'watcher.log'

function Write-Log([string]$testo) {
    # Il log del watcher attivo e' tenuto aperto in esclusiva: se non si
    # riesce a scrivere si tira dritto. Un file occupato non deve
    # trasformare una decisione corretta in un'attivita' fallita.
    try {
        "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $testo" |
            Out-File $log -Append -Encoding utf8 -ErrorAction Stop
    } catch {
        Write-Output $testo
    }
}

$repo = Split-Path -Parent $PSScriptRoot
$exe = Join-Path $repo '.venv\Scripts\gigamail.exe'
if (-not (Test-Path $exe)) {
    throw "gigamail.exe non trovato in $exe"
}

# Un watcher alla volta. Fermare l'attivita' pianificata NON uccide
# l'albero di processi che ha lanciato, e la console puo' averne avviato
# uno per conto suo: senza questo controllo un riavvio del task lascia due
# watcher sulle stesse regole, a contendersi le stesse mail. Il watcher
# registra pid e battito a ogni giro, quindi qui basta chiederglielo — la
# stessa verifica che fa la console prima di avviarne uno.
$vivo = & $exe watch-running 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Log "watcher gia' attivo ($vivo): non ne avvio un secondo"
    exit 0
}

# Il log non deve crescere all'infinito su una macchina accesa per mesi:
# sopra i 5 MB si tiene solo il giro precedente.
try {
    if ((Test-Path $log) -and ((Get-Item $log).Length -gt 5MB)) {
        Move-Item $log "$log.1" -Force
    }
} catch { }

$env:PYTHONIOENCODING = 'utf-8'
# Senza questo Python bufferizza l'output rediretto su file e il log
# resta vuoto per ore: inutile proprio nel momento in cui lo apri per
# capire perche' una regola non e' scattata.
$env:PYTHONUNBUFFERED = '1'

Write-Log '=== avvio ==='
& $exe watch --interval 120 --verbose *>&1 | Out-File $log -Append -Encoding utf8
