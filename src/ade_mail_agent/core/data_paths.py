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
    GIGAMAIL_ROOT      sposta l'intera cartella dati (approvazioni, audit, mail)
    GIGAMAIL_DATA_DIR  sposta solo i dati mail (testing/Electron)
I nomi storici ADE_ROOT / ADE_MAIL_DATA_DIR restano alias: una config
esistente non si rompe mai. Se sono presenti entrambi, vince GIGAMAIL_*.
La cartella di default resta %APPDATA%\\ADE (~/.ade): rinominarla sarebbe
una migrazione dati senza beneficio.
"""

import os
from pathlib import Path


def _env(new: str, legacy: str) -> str:
    """Variabile col nome nuovo, o con l'alias storico. Vuoto = non impostata."""
    return (os.environ.get(new) or os.environ.get(legacy) or "").strip()


def app_root() -> Path:
    """Cartella applicativa: approvals.db, agent_audit.jsonl, agent.json.
    Override: GIGAMAIL_ROOT (alias ADE_ROOT)."""
    override = _env("GIGAMAIL_ROOT", "ADE_ROOT")
    if override:
        root = Path(override)
    else:
        appdata = os.environ.get("APPDATA")  # Windows
        root = Path(appdata) / "ADE" if appdata else Path.home() / ".ade"
    root.mkdir(parents=True, exist_ok=True)
    return root


def data_root() -> Path:
    """Root scrivibile per i dati mail (DB, cache, token, log).
    Override: GIGAMAIL_DATA_DIR (alias ADE_MAIL_DATA_DIR); altrimenti
    app_root()/mail."""
    override = _env("GIGAMAIL_DATA_DIR", "ADE_MAIL_DATA_DIR")
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
