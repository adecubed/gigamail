"""
sent_cache.py — Cache locale delle ultime N mail inviate per account.

Salva in cache/sent_cache_{account_id}.json accanto a questo file.
Thread background aggiorna ogni REFRESH_INTERVAL secondi.
smart_draft legge il JSON locale invece di chiamare IMAP ogni volta.
"""

import os
import json
import threading
import time
from pathlib import Path
from typing import List, Dict, Optional

from data_paths import cache_dir as _resolve_cache_dir

# ── CONFIG ──────────────────────────────────────────────────────────
CACHE_DIR        = _resolve_cache_dir()
TOP_MESSAGES     = 20          # quante inviate tenere in cache
REFRESH_INTERVAL = 600         # aggiorna ogni 10 minuti
MAX_AGE_SECONDS  = 3600        # considera la cache stale dopo 1 ora


def _cache_path(account_id: int) -> Path:
    return CACHE_DIR / f"sent_cache_{account_id}.json"


def _ensure_cache_dir():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


# ── LETTURA ──────────────────────────────────────────────────────────

def get_sent_cached(account_id: int) -> Optional[List[Dict]]:
    """
    Ritorna le ultime N inviate dalla cache locale.
    Ritorna None se la cache non esiste o è troppo vecchia (fallback a IMAP).
    """
    path = _cache_path(account_id)
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Controlla età
        updated_at = data.get("updated_at", 0)
        age = time.time() - updated_at
        if age > MAX_AGE_SECONDS:
            print(f"[SENT CACHE] account {account_id} — cache stale ({int(age)}s), fallback IMAP")
            return None
        messages = data.get("messages", [])
        print(f"[SENT CACHE] account {account_id} — {len(messages)} messaggi da cache ({int(age)}s fa)")
        return messages
    except Exception as e:
        print(f"[SENT CACHE] errore lettura account {account_id}: {e}")
        return None


# ── SCRITTURA ────────────────────────────────────────────────────────

def update_sent_cache(account_id: int, messages: List[Dict]) -> bool:
    """
    Salva le inviate in cache. Ritorna True se OK.
    Salva solo i campi necessari per smart_draft (subject, body, bodyPreview).
    """
    _ensure_cache_dir()
    path = _cache_path(account_id)
    try:
        # Tieni solo i campi che servono — non salvare body HTML completo
        slim = []
        for m in messages[:TOP_MESSAGES]:
            slim.append({
                "subject":     m.get("subject", ""),
                "bodyPreview": m.get("bodyPreview", ""),
                "body":        {
                    "content": (m.get("body") or {}).get("content", "")[:2000]
                },
                "body_text":   (m.get("body_text") or "")[:2000],
                "from":        m.get("from", {}),
                "toRecipients": m.get("toRecipients", []),
                "receivedDateTime": m.get("receivedDateTime", ""),
            })
        data = {
            "account_id": account_id,
            "updated_at": time.time(),
            "count":      len(slim),
            "messages":   slim,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"[SENT CACHE] account {account_id} — cache aggiornata ({len(slim)} messaggi)")
        return True
    except Exception as e:
        print(f"[SENT CACHE] errore scrittura account {account_id}: {e}")
        return False


def invalidate_cache(account_id: int):
    """Elimina la cache di un account (es. dopo invio mail)."""
    path = _cache_path(account_id)
    try:
        if path.exists():
            path.unlink()
            print(f"[SENT CACHE] account {account_id} — cache invalidata")
    except Exception as e:
        print(f"[SENT CACHE] errore invalidazione account {account_id}: {e}")


# ── THREAD BACKGROUND ────────────────────────────────────────────────

_updater_thread: Optional[threading.Thread] = None
_stop_event = threading.Event()


def start_cache_updater(mail_router, get_all_account_ids_fn, interval: int = REFRESH_INTERVAL):
    """
    Avvia un thread background che aggiorna la cache delle inviate
    per tutti gli account ogni `interval` secondi.

    Parametri:
        mail_router           — istanza di MailRouter (ha get_messages)
        get_all_account_ids_fn — funzione callable che ritorna List[int] degli account_id attivi
        interval              — secondi tra un aggiornamento e l'altro (default 600)
    """
    global _updater_thread, _stop_event

    if _updater_thread and _updater_thread.is_alive():
        print("[SENT CACHE] updater già in esecuzione")
        return

    _stop_event.clear()

    def _loop():
        print("[SENT CACHE] updater avviato")
        # Prima passata immediata
        _refresh_all(mail_router, get_all_account_ids_fn)
        while not _stop_event.wait(interval):
            _refresh_all(mail_router, get_all_account_ids_fn)
        print("[SENT CACHE] updater fermato")

    _updater_thread = threading.Thread(target=_loop, daemon=True, name="sent-cache-updater")
    _updater_thread.start()


def stop_cache_updater():
    """Ferma il thread background."""
    _stop_event.set()


def _refresh_all(mail_router, get_all_account_ids_fn):
    """Aggiorna la cache per tutti gli account."""
    try:
        account_ids = get_all_account_ids_fn()
    except Exception as e:
        print(f"[SENT CACHE] errore get account ids: {e}")
        return

    for aid in account_ids:
        try:
            messages = mail_router.get_messages(aid, folder="sent", top=TOP_MESSAGES)
            if messages is not None:  # cache anche se sent vuoto, evita continui fallback IMAP
                update_sent_cache(aid, messages)
        except Exception as e:
            print(f"[SENT CACHE] errore fetch account {aid}: {e}")


def force_refresh(mail_router, account_id: int):
    """Aggiorna immediatamente la cache di un account specifico (es. dopo invio)."""
    try:
        messages = mail_router.get_messages(account_id, folder="sent", top=TOP_MESSAGES)
        if messages is not None:  # cache anche se sent vuoto
            update_sent_cache(account_id, messages)
    except Exception as e:
        print(f"[SENT CACHE] force_refresh account {account_id}: {e}")
