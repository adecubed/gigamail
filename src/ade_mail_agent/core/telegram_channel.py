# GigaMail — mail for your AI agent
# Copyright (C) 2026 Adecubed
# Licensed under the GNU AGPL v3 or later. See LICENSE.
"""Telegram come canale BIDIREZIONALE di approvazione (0.2).

Fino a ieri Telegram era solo un comando di notifica (B5: "solo notifica,
mai approvazione"). Il vincolo vero di ranbuman e' un altro: approvare
deve richiedere qualcosa che un processo NON PUO' DIGITARE. Un messaggio
che arriva DAL telefono dell'utente lo rispetta:

  - l'API Bot non permette di fabbricare messaggi da un utente: un
    processo sul PC, anche col token del bot in mano, scrive COME BOT,
    mai come l'utente. L'ancora e' la sessione Telegram del telefono —
    natura analoga a Windows Hello (chi ha il telefono sbloccato ≈ chi
    ha il PIN).
  - accettiamo comandi SOLO dal chat_id configurato; tutto il resto si
    ignora e si scrive nell'audit.
  - il token rubato permette di spiare le anteprime o silenziare il
    canale (DoS → fail-closed), NON di approvare. Dichiarato in
    SECURITY.md.
  - "approve": true e' opt-in esplicito, acceso da CLI dietro Hello.
    Senza, Telegram resta sola notifica + rifiuto (dire no e' sempre
    sicuro).

Configurazione: blocco "telegram" in notify.json (accanto ad agent.json):
  {"telegram": {"token": "...", "chat_id": 123, "approve": true}}
Nessuna libreria Telegram: quattro chiamate HTTP con `requests`.
"""
import json
from typing import Any, Dict, List, Optional

import requests

_API = "https://api.telegram.org/bot{token}/{method}"
_TIMEOUT = 15


def _config_path():
    from ade_mail_agent.core.data_paths import app_root
    return app_root() / "notify.json"


def load_config() -> Optional[Dict[str, Any]]:
    """{token, chat_id, approve} o None se Telegram non e' configurato."""
    try:
        with open(_config_path(), encoding="utf-8-sig") as f:
            tg = (json.load(f) or {}).get("telegram") or {}
    except Exception:
        return None
    token = str(tg.get("token") or "").strip()
    try:
        chat_id = int(tg.get("chat_id"))
    except (TypeError, ValueError):
        return None
    if not token or not chat_id:
        return None
    return {"token": token, "chat_id": chat_id,
            "approve": bool(tg.get("approve", False))}


def save_config(token: str, chat_id: int, approve: bool) -> None:
    """Scrive il blocco telegram preservando il resto di notify.json.
    Se c'era un `command` curl verso api.telegram.org lo toglie: il canale
    nativo lo sostituisce (altrimenti ogni avviso arriverebbe doppio)."""
    path = _config_path()
    data: Dict[str, Any] = {}
    try:
        with open(path, encoding="utf-8-sig") as f:
            data = json.load(f) or {}
    except Exception:
        data = {}
    cmd = data.get("command")
    if isinstance(cmd, list) and any("api.telegram.org" in str(c) for c in cmd):
        data.pop("command", None)
    data["telegram"] = {"token": token, "chat_id": int(chat_id),
                        "approve": bool(approve)}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


class Telegram:
    def __init__(self, cfg: Dict[str, Any]):
        self.token = cfg["token"]
        self.chat_id = int(cfg["chat_id"])
        self.approve_enabled = bool(cfg.get("approve", False))

    def _call(self, method: str, http_timeout: float = _TIMEOUT, **params) -> Optional[Dict[str, Any]]:
        try:
            r = requests.post(_API.format(token=self.token, method=method),
                              json=params, timeout=http_timeout)
            data = r.json()
            if not data.get("ok"):
                return None
            return data
        except Exception:
            return None

    # ------------------------------------------------------------ out

    def send_to(self, chat_id: int, text: str) -> bool:
        """Messaggio a una chat specifica: serve per avvisare la chat
        fidata PRECEDENTE quando qualcuno cambia il chat_id configurato."""
        return self._call("sendMessage", chat_id=int(chat_id),
                          text=text[:4000]) is not None

    def send(self, text: str,
             buttons: Optional[List[List[Dict[str, str]]]] = None,
             html: bool = False) -> bool:
        """`html=True` per i testi passati da safe_html(): senza
        parse_mode Telegram linkifica da solo indirizzi e URL del
        messaggio, e in un'approvazione l'unica cosa tappabile
        diventa il mailto: del destinatario."""
        params: Dict[str, Any] = {"chat_id": self.chat_id, "text": text[:4000]}
        if html:
            params["parse_mode"] = "HTML"
        if buttons:
            params["reply_markup"] = {"inline_keyboard": buttons}
        return self._call("sendMessage", **params) is not None

    @staticmethod
    def safe_html(text: str) -> str:
        """Testo per Telegram in cui niente diventa un link.

        Telegram riconosce da solo indirizzi email e URL nel testo e
        li rende tappabili. In un messaggio di approvazione senza
        bottoni il risultato e' che l'unica cosa premibile e' il
        `mailto:` del destinatario: aprirlo lancia il client di posta
        del telefono e chiede di autenticarsi. Indirizzi e URL vanno
        quindi in <code>, che Telegram non linkifica, cosi' le
        uniche cose da premere restano i bottoni."""
        import re as _re
        esc = (text.replace("&", "&amp;").replace("<", "&lt;")
                   .replace(">", "&gt;"))
        pat = _re.compile(r"(https?://\S+|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,})")
        return pat.sub(lambda m: f"<code>{m.group(1)}</code>", esc)

    @staticmethod
    def action_buttons(request_id: str, lang: str, can_approve: bool) -> List[List[Dict[str, str]]]:
        """Bottoni sotto una bozza semi. callback_data <= 64 byte."""
        it = lang == "it"
        row = []
        if can_approve:
            row.append({"text": "✅ " + ("Approva" if it else "Approve"),
                        "callback_data": f"a:{request_id}"})
        row.append({"text": "❌ " + ("Rifiuta" if it else "Reject"),
                    "callback_data": f"r:{request_id}"})
        row.append({"text": "✏️ " + ("Modifica" if it else "Edit"),
                    "callback_data": f"m:{request_id}"})
        return [row]

    def delete_message(self, message_id: int) -> bool:
        """Cancella un messaggio dalla chat. Usato per il PIN: un PIN
        scritto in chat resta nella cronologia e sui server di
        Telegram, e chiunque riapra la conversazione lo legge. Non e'
        una garanzia — Telegram puo' rifiutare, e altri client
        possono averlo gia' visto — ma non lasciarlo li' e' il minimo."""
        if not message_id:
            return False
        return self._call("deleteMessage", chat_id=self.chat_id,
                          message_id=int(message_id)) is not None

    def clear_buttons(self, message_id: int) -> bool:
        """Toglie la tastiera da un messaggio gia' mandato.

        Una richiesta scade dopo 15 minuti ma il messaggio resta in
        chat per sempre, con i suoi tre bottoni: si continua a
        premerli e a farsi rispondere di no. Tolti i bottoni, il
        messaggio resta come storico e smette di promettere azioni."""
        if not message_id:
            return False
        return self._call("editMessageReplyMarkup",
                          chat_id=self.chat_id,
                          message_id=int(message_id),
                          reply_markup={"inline_keyboard": []}) is not None

    def answer_callback(self, callback_id: str, text: str = "") -> None:
        self._call("answerCallbackQuery", callback_query_id=callback_id,
                   text=text[:200])

    # ------------------------------------------------------------- in

    def poll(self, offset: int, timeout: int = 0) -> tuple:
        """Long-poll di getUpdates. Ritorna (eventi, nuovo_offset).
        Ogni evento: {kind: 'callback'|'text', chat_id, data|text,
        callback_id}. Gli eventi di ALTRI chat_id vengono restituiti con
        chat_id diverso: e' il chiamante a ignorarli (e ad auditarli)."""
        params: Dict[str, Any] = {"offset": offset,
                                  "allowed_updates": ["message", "callback_query"]}
        if timeout:
            params["timeout"] = int(timeout)
        data = self._call("getUpdates", http_timeout=timeout + _TIMEOUT, **params)
        if not data:
            return [], offset
        events = []
        new_offset = offset
        for upd in data.get("result") or []:
            new_offset = max(new_offset, int(upd.get("update_id", 0)) + 1)
            cq = upd.get("callback_query")
            if cq:
                events.append({
                    "kind": "callback",
                    "chat_id": int(((cq.get("message") or {}).get("chat") or {}).get("id") or 0),
                    "from_id": int((cq.get("from") or {}).get("id") or 0),
                    "data": str(cq.get("data") or ""),
                    "callback_id": str(cq.get("id") or ""),
                    # da quale messaggio arriva il tap: serve a
                    # togliergli i bottoni quando non c'e' piu' niente
                    # da premere.
                    "message_id": int((cq.get("message") or {}).get("message_id") or 0),
                })
                continue
            msg = upd.get("message") or {}
            if msg.get("text"):
                events.append({
                    "kind": "text",
                    "chat_id": int((msg.get("chat") or {}).get("id") or 0),
                    "from_id": int((msg.get("from") or {}).get("id") or 0),
                    "text": str(msg["text"]),
                    # serve a cancellare dalla chat il messaggio che
                    # contiene il PIN
                    "message_id": int(msg.get("message_id") or 0),
                })
        return events, new_offset

    def is_trusted(self, event: Dict[str, Any]) -> bool:
        """Solo la chat configurata, e solo se chi preme e' lo stesso
        utente (in una chat privata coincidono; in un gruppo no — e un
        gruppo non e' un dispositivo di approvazione)."""
        return (event.get("chat_id") == self.chat_id
                and event.get("from_id") == self.chat_id)


def channel() -> Optional[Telegram]:
    cfg = load_config()
    return Telegram(cfg) if cfg else None
