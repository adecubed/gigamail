"""
data_paths.py — Sorgente unica per i path scrivibili di ADE Mail.

In produzione l'app gira da C:\\Program Files\\... (read-only) e NON può scrivere
accanto al codice. Tutti i file di dati (DB, cache, token, log) vanno in:
    %APPDATA%\\ADE\\mail\\          (Windows)
    ~/.ade/mail/                     (Linux/macOS)

Override per testing/Electron: variabile d'ambiente ADE_MAIL_DATA_DIR.
"""

import os
from pathlib import Path


def data_root() -> Path:
    """Root scrivibile per tutti i dati di ADE Mail. Crea la cartella se non esiste."""
    override = os.environ.get("ADE_MAIL_DATA_DIR")
    if override:
        root = Path(override)
    else:
        appdata = os.environ.get("APPDATA")  # Windows
        if appdata:
            root = Path(appdata) / "ADE" / "mail"
        else:
            root = Path.home() / ".ade" / "mail"
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
