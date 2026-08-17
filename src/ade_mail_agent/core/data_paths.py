"""
data_paths.py — Sorgente unica per i path scrivibili di ADE Mail.

In produzione l'app gira da C:\\Program Files\\... (read-only) e NON può scrivere
accanto al codice. Tutti i file di dati (DB, cache, token, log) vanno in:
    %APPDATA%\\ADE\\           (Windows)
    ~/.ade/                    (Linux/macOS)
con la posta nella sottocartella mail/.

Questo modulo è l'UNICA fonte dei percorsi: nessun altro modulo legge
APPDATA direttamente. Client MCP che filtrano l'ambiente (es. Hermes passa
solo un baseline di variabili) possono redirigere tutto con una variabile:
    ADE_ROOT           sposta l'intera cartella ADE (approvazioni, audit, mail)
    ADE_MAIL_DATA_DIR  sposta solo i dati mail (testing/Electron)
"""

import os
from pathlib import Path


def app_root() -> Path:
    """Cartella applicativa ADE: approvals.db, agent_audit.jsonl, agent.json.
    Override: ADE_ROOT."""
    override = os.environ.get("ADE_ROOT")
    if override:
        root = Path(override)
    else:
        appdata = os.environ.get("APPDATA")  # Windows
        root = Path(appdata) / "ADE" if appdata else Path.home() / ".ade"
    root.mkdir(parents=True, exist_ok=True)
    return root


def data_root() -> Path:
    """Root scrivibile per i dati mail (DB, cache, token, log).
    Override: ADE_MAIL_DATA_DIR; altrimenti segue app_root()/mail."""
    override = os.environ.get("ADE_MAIL_DATA_DIR")
    root = Path(override) if override else app_root() / "mail"
    root.mkdir(parents=True, exist_ok=True)
    return root


def cache_dir() -> Path:
    """Sottocartella per le cache (sent_cache, identity_cache, ecc.)."""
    p = data_root() / "cache"
    p.mkdir(parents=True, exist_ok=True)
    return p


def db_path(name: str) -> Path:
    """Path di un file DB (es. '.mail_memory.db', '.accounts.db')."""
    return data_root() / name


def token_path(name: str = ".token_cache.json") -> Path:
    """Path di un file token (es. MSAL cache)."""
    return data_root() / name


def log_path(name: str = "ade_mail_server.log") -> Path:
    """Path del log del server."""
    return data_root() / name


def env_path(name: str = ".env") -> Path:
    """Path del file env utente, fuori dalla directory applicazione."""
    return data_root() / name
