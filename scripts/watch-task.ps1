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

$repo = Split-Path -Parent $PSScriptRoot
$exe = Join-Path $repo '.venv\Scripts\gigamail.exe'
if (-not (Test-Path $exe)) {
    throw "gigamail.exe non trovato in $exe"
}

$log = Join-Path $env:GIGAMAIL_ROOT 'watcher.log'
# Il log non deve crescere all'infinito su una macchina che sta accesa
# per mesi: sopra i 5 MB si tiene solo il giro precedente.
if ((Test-Path $log) -and ((Get-Item $log).Length -gt 5MB)) {
    Move-Item $log "$log.1" -Force
}

$env:PYTHONIOENCODING = 'utf-8'
# Senza questo Python bufferizza l'output rediretto su file e il log
# resta vuoto per ore: inutile proprio nel momento in cui lo apri per
# capire perche' una regola non e' scattata.
$env:PYTHONUNBUFFERED = '1'
"=== avvio $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ===" | Out-File $log -Append -Encoding utf8

& $exe watch --interval 120 --verbose *>&1 | Out-File $log -Append -Encoding utf8
