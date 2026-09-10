# GigaMail — mail for your AI agent
# Copyright (C) 2026 Adecubed
# Licensed under the GNU AGPL v3 or later. See LICENSE.
"""Una casella finta su file, per le riprese e per le prove.

Serve a far vedere il prodotto vero senza collegare la posta di qualcuno:
la console, il server MCP e le regole passano dallo STESSO codice, solo che
sotto invece di IMAP o Graph c'e' un JSON su disco. Nessuna connessione di
rete, nessuna credenziale, nessun messaggio che esce davvero: cio' che
l'agente 'invia' finisce nella posta inviata del file.

Non e' una modalita' globale e non si accende con una variabile
d'ambiente: esiste solo se qualcuno crea un account di tipo 'demo'. Chi
non ne ha uno non ha nemmeno il codice sul percorso. Nel pacchetto
dell'installer non viene creato nessun account demo.

Il file di partenza (il seme) e' di sola lettura; la copia su cui si lavora
sta nella cartella dati dell'app, cosi' `reset()` riporta la casella
all'inizio fra una ripresa e l'altra.
"""
import base64
import json
import os
import shutil
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from .data_paths import app_root

# Le cartelle di sistema, con il nome che la console si aspetta.
CARTELLE_BASE = [
    {"id": "inbox", "name": "inbox", "displayName": "Posta in arrivo"},
    {"id": "sentitems", "name": "sentitems", "displayName": "Posta inviata"},
    {"id": "drafts", "name": "drafts", "displayName": "Bozze"},
    {"id": "deleteditems", "name": "deleteditems", "displayName": "Cestino"},
]

_ALIAS = {
    "posta_in_arrivo": "inbox", "postainarrivo": "inbox", "INBOX": "inbox",
    "sent": "sentitems", "postainviata": "sentitems", "posta_inviata": "sentitems",
    "draft": "drafts", "bozze": "drafts",
    "trash": "deleteditems", "cestino": "deleteditems", "deleted": "deleteditems",
    "junk": "junkemail", "spam": "junkemail", "postaindesiderata": "junkemail",
}


def normalizza_cartella(folder: str) -> str:
    f = (folder or "inbox").strip()
    if f in _ALIAS:
        return _ALIAS[f]
    basso = f.lower()
    return _ALIAS.get(basso, f if f else "inbox")


# ── Il file della casella ────────────────────────────────────────────

def percorso_stato(account_id: int) -> str:
    """La copia di lavoro, dentro la cartella dati dell'app."""
    base = os.path.join(str(app_root()), "demo-mailbox")
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, f"{int(account_id)}.json")


def _seme(a: dict) -> str:
    return (a.get("data") or {}).get("seed_path") or ""


def reset(a: dict) -> str:
    """Riporta la casella al seme. Fra una ripresa e l'altra si rilancia
    questo e la scena riparte identica."""
    stato = percorso_stato(a.get("id"))
    seme = _seme(a)
    if seme and os.path.exists(seme):
        shutil.copyfile(seme, stato)
    elif os.path.exists(stato):
        os.unlink(stato)
    return stato


def _carica(a: dict) -> dict:
    stato = percorso_stato(a.get("id"))
    if not os.path.exists(stato):
        reset(a)
    if not os.path.exists(stato):
        return {"messages": [], "folders": []}
    with open(stato, encoding="utf-8") as f:
        box = json.load(f)
    box.setdefault("messages", [])
    box.setdefault("folders", [])
    return box


def _salva(a: dict, box: dict) -> None:
    stato = percorso_stato(a.get("id"))
    tmp = stato + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(box, f, ensure_ascii=False, indent=2)
    os.replace(tmp, stato)


# ── Da record a messaggio nella forma che i chiamanti conoscono ───────

def _mittente(m: dict) -> dict:
    f = m.get("from") or {}
    return {"emailAddress": {"name": f.get("name", ""),
                             "address": f.get("address", "")}}


def _destinatari(m: dict) -> List[dict]:
    return [{"emailAddress": {"name": "", "address": r}}
            for r in (m.get("to") or [])]


def _anteprima(m: dict) -> str:
    return " ".join((m.get("body") or "").split())[:200]


def _sintesi(m: dict) -> dict:
    """La forma della lista: quella che la console mostra in colonna."""
    return {
        "id": str(m.get("id")),
        "subject": m.get("subject", ""),
        "from": _mittente(m),
        "receivedDateTime": m.get("receivedDateTime", ""),
        "bodyPreview": _anteprima(m),
        "isRead": bool(m.get("isRead")),
        "hasAttachments": bool(m.get("attachments")),
        "folder": m.get("folder", "inbox"),
    }


def _completo(m: dict) -> dict:
    corpo = m.get("body") or ""
    return {
        "id": str(m.get("id")),
        "subject": m.get("subject", ""),
        "from": _mittente(m),
        "receivedDateTime": m.get("receivedDateTime", ""),
        "body": {"contentType": "text", "content": corpo},
        "body_text": corpo[:4000],
        "bodyPreview": _anteprima(m),
        "isRead": bool(m.get("isRead")),
        "attachments": list(m.get("attachments") or []),
        "hasAttachments": bool(m.get("attachments")),
        "toRecipients": _destinatari(m),
        "ccRecipients": [],
        "folder": m.get("folder", "inbox"),
    }


def _trova(box: dict, message_id: str) -> Optional[dict]:
    for m in box["messages"]:
        if str(m.get("id")) == str(message_id):
            return m
    return None


# ── Lettura ──────────────────────────────────────────────────────────

def get_messages(a: dict, folder: str = "inbox", top: int = 20,
                 skip: int = 0) -> List[Dict]:
    box = _carica(a)
    target = normalizza_cartella(folder)
    scelti = [m for m in box["messages"]
              if normalizza_cartella(m.get("folder", "inbox")) == target]
    scelti.sort(key=lambda m: str(m.get("receivedDateTime", "")), reverse=True)
    return [_sintesi(m) for m in scelti[skip:skip + max(int(top or 20), 1)]]


def get_message(a: dict, message_id: str) -> Dict:
    m = _trova(_carica(a), message_id)
    return _completo(m) if m else {}


def get_message_headers(a: dict, message_id: str) -> Optional[Dict]:
    """Intestazioni per le barriere anti-spam. La casella finta produce
    posta autenticata e non automatica: le barriere devono dire di si',
    altrimenti in ripresa non parte niente e sembra un guasto."""
    m = _trova(_carica(a), message_id)
    if not m:
        return None
    mittente = (m.get("from") or {}).get("address", "")
    dominio = mittente.split("@")[-1] if "@" in mittente else "example.com"
    return {
        "from": [mittente],
        "to": [", ".join(m.get("to") or [])],
        "subject": [m.get("subject", "")],
        "date": [m.get("receivedDateTime", "")],
        "authentication-results": [
            f"demo.local; dmarc=pass header.from={dominio}; "
            f"spf=pass; dkim=pass"
        ],
        "message-id": [f"<{m.get('id')}@demo.local>"],
    }


def search_messages(a: dict, query: str = "", top: int = 10) -> List[Dict]:
    q = (query or "").strip().lower()
    box = _carica(a)
    if not q:
        return []
    fuori = []
    for m in box["messages"]:
        campi = " ".join([
            m.get("subject", ""), m.get("body", ""),
            (m.get("from") or {}).get("address", ""),
            (m.get("from") or {}).get("name", ""),
        ]).lower()
        if q in campi:
            fuori.append(_sintesi(m))
    fuori.sort(key=lambda m: str(m.get("receivedDateTime", "")), reverse=True)
    return fuori[:max(int(top or 10), 1)]


def get_all_uids(a: dict, folder: str = "inbox") -> List[str]:
    target = normalizza_cartella(folder)
    return [str(m.get("id")) for m in _carica(a)["messages"]
            if normalizza_cartella(m.get("folder", "inbox")) == target]


def fetch_messages_by_uids(a: dict, uids: List[str]) -> List[Dict]:
    box = _carica(a)
    voluti = {str(u) for u in (uids or [])}
    return [_sintesi(m) for m in box["messages"] if str(m.get("id")) in voluti]


def list_folders(a: dict) -> List[Dict]:
    box = _carica(a)
    viste = {c["id"] for c in CARTELLE_BASE}
    fuori = list(CARTELLE_BASE)
    for c in box.get("folders") or []:
        if c.get("id") not in viste:
            fuori.append({"id": c["id"], "name": c.get("name", c["id"]),
                          "displayName": c.get("displayName", c["id"])})
            viste.add(c["id"])
    return fuori


def get_attachment(a: dict, message_id: str, filename: str) -> tuple:
    """Ritorna (bytes, content_type). Gli allegati della casella finta
    portano il contenuto in base64 dentro il record."""
    m = _trova(_carica(a), message_id)
    for att in (m or {}).get("attachments") or []:
        if att.get("name") == filename:
            grezzo = att.get("contentBytes") or ""
            return base64.b64decode(grezzo), att.get("contentType",
                                                     "application/octet-stream")
    raise ValueError(f"Allegato '{filename}' non trovato")


# ── Scrittura ────────────────────────────────────────────────────────

def set_read_status(a: dict, message_id: str, is_read: bool = True) -> bool:
    box = _carica(a)
    m = _trova(box, message_id)
    if not m:
        return False
    m["isRead"] = bool(is_read)
    _salva(a, box)
    return True


def move_to_folder(a: dict, message_id: str, folder_id: str) -> bool:
    box = _carica(a)
    m = _trova(box, message_id)
    if not m:
        return False
    m["folder"] = normalizza_cartella(folder_id)
    _salva(a, box)
    return True


def delete_message(a: dict, message_id: str) -> bool:
    """Nel cestino, non via dal disco: la demo non deve poter far sparire
    niente per sbaglio davanti alla telecamera."""
    return move_to_folder(a, message_id, "deleteditems")


def create_folder(a: dict, name: str) -> Dict:
    box = _carica(a)
    nome = (name or "").strip()
    if not nome:
        return {}
    esistenti = {c.get("id") for c in box.get("folders") or []}
    if nome not in esistenti:
        box.setdefault("folders", []).append(
            {"id": nome, "name": nome, "displayName": nome})
        _salva(a, box)
    return {"id": nome, "name": nome, "displayName": nome}


def delete_folder(a: dict, folder_id: str) -> bool:
    box = _carica(a)
    prima = len(box.get("folders") or [])
    box["folders"] = [c for c in box.get("folders") or []
                      if c.get("id") != folder_id]
    for m in box["messages"]:
        if m.get("folder") == folder_id:
            m["folder"] = "inbox"
    _salva(a, box)
    return len(box["folders"]) < prima


def send_message(a: dict, to: str = "", subject: str = "", body: str = "",
                 reply_to_id: str = None, attachments: list = None,
                 cc: list = None, bcc: list = None) -> Dict:
    """Non esce niente da questa macchina: il messaggio finisce nella posta
    inviata del file. La forma del risultato e' quella che si aspetta
    _normalize_send_result, cosi' la console e l'audit non vedono
    differenze."""
    box = _carica(a)
    nuovo_id = str(max([int(m.get("id", 0)) for m in box["messages"]] or [1000]) + 1)
    destinatari = [d.strip() for d in str(to or "").replace(";", ",").split(",")
                   if d.strip()]
    box["messages"].append({
        "id": nuovo_id,
        "folder": "sentitems",
        "subject": subject,
        "from": {"name": a.get("name", ""), "address": a.get("email", "")},
        "to": destinatari,
        "cc": list(cc or []),
        "receivedDateTime": datetime.now(timezone.utc)
                            .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "body": body,
        "isRead": True,
        "in_reply_to": reply_to_id,
        "attachments": [{"name": os.path.basename(str(p))}
                        for p in (attachments or [])],
    })
    _salva(a, box)
    return {
        "success": True,
        "provider": "demo",
        "sent_copy_saved": True,
        "warning": None,
        "error": None,
        "provider_result": {"accepted": destinatari, "rejected": []},
        "message_id": nuovo_id,
    }


# ── Il seme ──────────────────────────────────────────────────────────

def scrivi_seme(path: str, messaggi: List[dict],
                cartelle: Optional[List[dict]] = None,
                da_quanti_minuti: Optional[List[int]] = None) -> str:
    """Scrive il file di partenza. Le date sono relative a ADESSO: una
    casella con la posta di due anni fa, in ripresa, si vede."""
    ora = datetime.now(timezone.utc)
    fuori = []
    for i, m in enumerate(messaggi):
        minuti = (da_quanti_minuti or [])[i] if i < len(da_quanti_minuti or []) else (i + 1) * 47
        rec = dict(m)
        rec.setdefault("id", str(1001 + i))
        rec.setdefault("folder", "inbox")
        rec.setdefault("isRead", False)
        rec.setdefault("attachments", [])
        rec["receivedDateTime"] = (ora - timedelta(minutes=minuti)).strftime(
            "%Y-%m-%dT%H:%M:%SZ")
        fuori.append(rec)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"messages": fuori, "folders": list(cartelle or [])},
                  f, ensure_ascii=False, indent=2)
    return path
