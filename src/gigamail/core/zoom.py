# GigaMail — mail for your AI agent
# Copyright (C) 2026 Adecubed
# Licensed under the GNU AGPL v3 or later. See LICENSE.
"""Zoom: riunioni create sull'account Zoom dell'utente.

Autenticazione Server-to-Server OAuth: un'app privata che l'utente crea
nel Marketplace di Zoom, con Account ID, Client ID e Client Secret. Niente
login interattivo e niente token da rinnovare a mano: il token dura un'ora
e si richiede da solo quando scade.

Il segreto non passa mai da un argomento ne' da un file in chiaro: si
digita in `gigamail zoom setup` e resta cifrato come le password degli
account.

Creare una riunione non manda nulla a nessuno: Zoom non invita i
partecipanti se non glielo si chiede. Il link arriva al cliente solo con
una mail, e le mail passano dall'approvazione.
"""
import time
from typing import Any, Dict, Optional

import requests

from . import accounts

TOKEN_URL = "https://zoom.us/oauth/token"
API_URL = "https://api.zoom.us/v2"
FUSO = "Europe/Rome"
_TIMEOUT = 20
_CHIAVI = ("zoom_account_id", "zoom_client_id", "zoom_client_secret_enc")
_token: Dict[str, Any] = {}


class ZoomNonConfigurato(Exception):
    """Mancano le credenziali: `gigamail zoom setup`."""


class ZoomErrore(Exception):
    """Zoom ha risposto con un errore, o non ha risposto."""


def config() -> Optional[Dict[str, str]]:
    """Le credenziali, o None se Zoom non e' collegato. Un segreto che non
    si decifra (chiave cambiata, file copiato da un altro PC) vale come
    assente: meglio chiedere un nuovo setup che chiamare Zoom con spazzatura."""
    try:
        account_id = accounts.get_setting("zoom_account_id", "").strip()
        client_id = accounts.get_setting("zoom_client_id", "").strip()
        cifrato = accounts.get_setting("zoom_client_secret_enc", "").strip()
    except Exception:
        return None
    if not (account_id and client_id and cifrato):
        return None
    try:
        segreto = accounts._decrypt(cifrato)
    except Exception:
        return None
    return {"account_id": account_id, "client_id": client_id,
            "client_secret": segreto}


def configurato() -> bool:
    return config() is not None


def salva_config(account_id: str, client_id: str, client_secret: str) -> None:
    accounts.set_setting("zoom_account_id", account_id.strip())
    accounts.set_setting("zoom_client_id", client_id.strip())
    accounts.set_setting("zoom_client_secret_enc",
                         accounts._encrypt(client_secret.strip()))
    _token.clear()


def rimuovi_config() -> None:
    for chiave in _CHIAVI:
        accounts.set_setting(chiave, "")
    _token.clear()


def _breve(risposta) -> str:
    try:
        dato = risposta.json() or {}
        return str(dato.get("message") or dato.get("reason") or dato)[:200]
    except Exception:
        return str(getattr(risposta, "text", ""))[:200]


def _richiedi_token(cfg: Dict[str, str]) -> str:
    adesso = time.time()
    if (_token.get("valore") and _token.get("client_id") == cfg["client_id"]
            and _token.get("scade", 0) > adesso + 60):
        return _token["valore"]
    try:
        r = requests.request(
            "POST", TOKEN_URL,
            params={"grant_type": "account_credentials",
                    "account_id": cfg["account_id"]},
            auth=(cfg["client_id"], cfg["client_secret"]),
            timeout=_TIMEOUT)
    except requests.RequestException as e:
        raise ZoomErrore(f"Zoom non raggiungibile: {e}") from e
    if r.status_code != 200:
        raise ZoomErrore(
            f"credenziali Zoom rifiutate ({r.status_code}): {_breve(r)}")
    dato = r.json() or {}
    valore = str(dato.get("access_token") or "")
    if not valore:
        raise ZoomErrore("Zoom non ha restituito un token")
    _token.update(valore=valore, client_id=cfg["client_id"],
                  scade=adesso + float(dato.get("expires_in") or 3600))
    return valore


def _chiama(metodo: str, percorso: str, **kw) -> Dict[str, Any]:
    cfg = config()
    if cfg is None:
        raise ZoomNonConfigurato(
            "Zoom non collegato: collegalo dalla console "
            "(Aggiungi account > Zoom).")
    for tentativo in range(2):
        token = _richiedi_token(cfg)
        try:
            r = requests.request(
                metodo, API_URL + percorso,
                headers={"Authorization": f"Bearer {token}"},
                timeout=_TIMEOUT, **kw)
        except requests.RequestException as e:
            raise ZoomErrore(f"Zoom non raggiungibile: {e}") from e
        if r.status_code == 401 and tentativo == 0:
            # Token revocato o scaduto prima del previsto: se ne chiede
            # uno nuovo una volta sola, poi l'errore resta un errore.
            _token.clear()
            continue
        break
    if r.status_code >= 400:
        raise ZoomErrore(
            f"Zoom {metodo} {percorso}: {r.status_code} {_breve(r)}")
    if r.status_code == 204 or not (getattr(r, "content", b"") or b"").strip():
        return {}
    return r.json() or {}


def _ora(inizio: str) -> str:
    testo = str(inizio or "").strip()[:19]
    return testo + ":00" if len(testo) == 16 else testo


def crea_riunione(argomento: str, inizio: str, durata_minuti: int = 60,
                  agenda: str = "") -> Dict[str, str]:
    """Riunione programmata, ora locale di Roma. La sala d'attesa e' accesa
    e nessuno entra prima dell'host: il link finisce in una mail, e una
    mail si inoltra."""
    dato = _chiama("POST", "/users/me/meetings", json={
        "topic": str(argomento or "Video call")[:200],
        "type": 2,
        "start_time": _ora(inizio),
        "timezone": FUSO,
        "duration": max(15, int(durata_minuti)),
        "agenda": str(agenda or "")[:2000],
        "settings": {"join_before_host": False, "waiting_room": True},
    })
    url = str(dato.get("join_url") or "")
    if not url or not dato.get("id"):
        raise ZoomErrore("Zoom ha creato la riunione senza link o senza id")
    return {"id": str(dato["id"]), "join_url": url,
            "password": str(dato.get("password") or "")}


def sposta_riunione(meeting_id: str, inizio: str,
                    durata_minuti: int = 60) -> None:
    _chiama("PATCH", f"/meetings/{meeting_id}", json={
        "start_time": _ora(inizio), "timezone": FUSO,
        "duration": max(15, int(durata_minuti))})


def cancella_riunione(meeting_id: str) -> bool:
    try:
        _chiama("DELETE", f"/meetings/{meeting_id}")
    except ZoomErrore as e:
        if " 404 " in str(e):
            return True  # gia' tolta: non c'e' niente da fare
        raise
    return True


def verifica() -> str:
    """L'indirizzo dell'utente Zoom collegato: prova che le credenziali
    funzionano davvero, non solo che sono state salvate."""
    return str(_chiama("GET", "/users/me").get("email") or "")
