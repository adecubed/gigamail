"""Rispondere a un cliente da Telegram.

L'avviso "il cliente ha risposto" arrivava su Telegram e li' finiva: per
rispondere bisognava tornare al PC, o chiedere a qualcuno di farlo. Ora
sotto l'avviso c'e' il bottone Rispondi, e si puo' anche rispondere
direttamente al messaggio dell'avviso. Quello che si scrive ("ok, va
bene") e' un'istruzione: la bozza la scrive l'agente, con identity, orari
liberi e presidio anti-injection come le bozze delle regole, e la mail
arriva in approvazione con i soliti bottoni. Niente parte senza un si'.

The same alert also reaches the desktop, with a Reply button that queues
the instruction for the watcher (process_desktop_queue). And when the
client names one precise time that is free in the calendar, the
confirmation is drafted straight away (draft_confirmation): it still waits
for approval like every other draft.
"""
import json
import secrets
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from gigamail import agent_bridge, policy
from gigamail.core import accounts, mail_router, signature
from gigamail.core import rules as rules_mod

from . import drafting
from .log import _log

# Le richieste nate qui si registrano nella tabella delle regole con questo
# rule_id: e' cosi' che il watcher le esegue dopo l'approvazione.
RULE_ID = "telegram-risposte"
AWAIT = "tg_await_istruzione"
_TTL_SECONDI = 4 * 3600
_KV_CTX = "tg_ctx_"
_KV_MSG = "tg_msg_"
_KV_REQ = "tg_req_"
_KV_DESKTOP = "desktop_reply_"


def _it(lang: str) -> bool:
    return (lang or "it") == "it"


def _say(tg, it: str, en: str) -> None:
    tg.send(it if _it(policy.user_lang()) else en)


def bottone(chiave: str, lang: str) -> List[List[Dict[str, str]]]:
    return [[{"text": "✍️ " + ("Rispondi" if _it(lang) else "Reply"),
              "callback_data": f"w:{chiave}"}]]


class DesktopChannel:
    """Stands in for Telegram when it is not configured, and for work
    queued from the desktop: messages become desktop notifications, and
    there are no buttons (approval happens from the approval toast)."""

    chat_id = "desktop"
    approve_enabled = False

    def send(self, text: str, buttons=None, html: bool = False) -> bool:
        try:
            from gigamail.core import desktop_notify
            return bool(desktop_notify.notify("GigaMail", text))
        except Exception:
            return False

    def send_message(self, text: str, buttons=None, html: bool = False) -> int:
        self.send(text)
        return 0

    @staticmethod
    def action_buttons(request_id: str, lang: str, can_approve: bool):
        return None

    def clear_buttons(self, message_id: int) -> bool:
        return True


def register_context(account_id: int, message: Dict[str, Any]) -> str:
    """Remember which mail a reply belongs to; returns the key the Reply
    buttons (Telegram and desktop) carry."""
    key = secrets.token_hex(4)
    f = message.get("from") or {}
    ea = f.get("emailAddress") if isinstance(f, dict) else None
    ea = ea if isinstance(ea, dict) else {}
    ctx = {"account_id": int(account_id),
           "message_id": str(message.get("id") or ""),
           "folder": "INBOX",
           "mittente": str(ea.get("address") or ""),
           "nome": str(ea.get("name") or "").strip().strip('"').strip(),
           "subject": str(message.get("subject") or "")}
    rules_mod.store().kv_set(_KV_CTX + key, json.dumps(ctx, ensure_ascii=False))
    return key


def notify_desktop(text: str, key: str) -> None:
    """The client-reply alert as a desktop notification. Its Reply button
    opens a window that asks what to answer and queues it for the
    watcher."""
    try:
        from gigamail.core import desktop_notify
        label = "Rispondi" if _it(policy.user_lang()) else "Reply"
        desktop_notify.notify("GigaMail", text,
                              actions=[(label, f"gigamail://reply/{key}")])
    except Exception as e:
        _log(f"client-reply alert not shown on the desktop: {e}", False)


def registra_avviso(tg, testo: str, account_id: int,
                    messaggio: Dict[str, Any], lang: str) -> str:
    """Manda l'avviso con il bottone Rispondi e ricorda a quale mail si
    riferisce, sia per il bottone sia per chi risponde al messaggio."""
    chiave = register_context(account_id, messaggio)
    rs = rules_mod.store()
    pulsanti = bottone(chiave, lang)
    if hasattr(tg, "send_message"):
        mid = tg.send_message(testo, buttons=pulsanti)
    else:
        mid = 0
        tg.send(testo, buttons=pulsanti)
    if mid:
        rs.kv_set(_KV_MSG + str(mid), chiave)
    return chiave


def contesto(chiave: str) -> Optional[Dict[str, Any]]:
    raw = rules_mod.store().kv_get(_KV_CTX + str(chiave or ""), "")
    try:
        return json.loads(raw) if raw else None
    except Exception:
        return None


def chiave_da_evento(ev: Dict[str, Any]) -> str:
    """La chiave dell'avviso a cui l'utente sta rispondendo, se risponde a uno."""
    rt = ev.get("reply_to")
    if not rt:
        return ""
    return rules_mod.store().kv_get(_KV_MSG + str(rt), "") or ""


def chiedi_istruzione(tg, chiave: str) -> None:
    ctx = contesto(chiave)
    if not ctx:
        _say(tg, "Questo avviso non si trova piu': non so a quale mail rispondere.",
             "This alert is no longer known: I don't know which mail to answer.")
        return
    rules_mod.store().kv_set(AWAIT, chiave)
    chi = ctx.get("nome") or ctx.get("mittente") or "?"
    _say(tg, f"✍️ Cosa rispondo a {chi}? Scrivi l'istruzione, per esempio «ok, va bene».",
         f"✍️ What should I reply to {chi}? Write the instruction, e.g. \"ok, fine\".")


def _doc_paths(account_id: int) -> List[str]:
    percorsi: List[str] = []
    for regola in rules_mod.store().active():
        if int(regola.get("account_id") or 0) != int(account_id):
            continue
        for p in regola.get("doc_paths") or []:
            if p not in percorsi:
                percorsi.append(p)
    return percorsi


def _cc(account_id: int) -> List[str]:
    from gigamail.core import video_call
    return video_call._cc(account_id)


def rispondi(w, tg, chiave: str, istruzione: str,
             previous_body: Optional[str] = None,
             feedback: Optional[str] = None,
             announce: bool = True) -> Optional[str]:
    """Bozza dall'istruzione, poi richiesta di approvazione. Ritorna la
    request_id, o None se non e' stato possibile prepararla (e lo dice)."""
    ctx = contesto(chiave)
    if not ctx:
        _say(tg, "Questo avviso non si trova piu': non so a quale mail rispondere.",
             "This alert is no longer known: I don't know which mail to answer.")
        return None
    istruzione = (istruzione or "").strip()
    if not istruzione:
        _say(tg, "Istruzione vuota: nessuna risposta preparata.",
             "Empty instruction: no reply prepared.")
        return None
    aid = int(ctx["account_id"])
    try:
        messaggio = mail_router.get_message(
            account_id=aid, message_id=ctx["message_id"], folder=ctx["folder"]) or {}
    except Exception as e:
        _log(f"telegram, mail non riletta ({ctx['message_id']}): {e}", True)
        messaggio = {}
    if not messaggio:
        _say(tg, "La mail non si trova piu' nella posta in arrivo: rispondi dal PC.",
             "The mail is no longer in the inbox: reply from the PC.")
        return None
    regola = {"rule_id": RULE_ID,
              "reply_style": ("ISTRUZIONE DELL'UTENTE, da seguire alla lettera "
                              f"nel contenuto: {istruzione}"),
              "doc_paths": _doc_paths(aid)}
    if announce:
        _say(tg, "⏳ Scrivo la risposta…", "⏳ Writing the reply…")
    try:
        corpo = drafting.draft_reply(regola, aid, messaggio, feedback=feedback,
                                     previous_body=previous_body)
    except drafting.MailConOrdini:
        _say(tg, "⚠️ La mail contiene istruzioni rivolte all'assistente: per "
                 "sicurezza rispondi dal PC.",
             "⚠️ The mail contains instructions aimed at the assistant: reply "
             "from the PC to be safe.")
        return None
    except agent_bridge.AgentUnavailable as e:
        _say(tg, f"⚠️ Non riesco a scrivere la bozza: {str(e)[:200]}",
             f"⚠️ I can't write the draft: {str(e)[:200]}")
        return None

    oggetto = " ".join(ctx["subject"].split())
    if not oggetto.lower().startswith("re:"):
        oggetto = f"Re: {oggetto}"
    cc = _cc(aid)
    corpo = signature.apply(aid, corpo)
    args = {"to": ctx["mittente"], "subject": oggetto, "body": corpo,
            "account_id": aid, "cc": cc, "message_id": ctx["message_id"]}
    nostro = accounts.get_account_by_id(aid) or {}
    preview = {"from": nostro.get("email"), "to": ctx["mittente"], "cc": cc,
               "bcc": [], **policy.describe_recipients(ctx["mittente"], cc, None),
               "subject": oggetto, "body": corpo}
    rid = policy.store().create("reply_mail", args, preview, ttl=_TTL_SECONDI)
    policy.audit("reply_mail", {"to": ctx["mittente"], "account_id": aid},
                 "approval_requested", detail="telegram")
    rs = rules_mod.store()
    rs.record(RULE_ID, aid, ctx["message_id"], ctx["mittente"],
              "awaiting_approval", "", rid)
    rs.kv_set(_KV_REQ + rid, json.dumps({"chiave": chiave, "istruzione": istruzione},
                                        ensure_ascii=False))
    from .telegram import approve_allowed
    chi = ctx.get("nome") or ctx["mittente"]
    policy.notify_approval_requested(
        rid, "reply_mail", preview,
        message=(f"✍️ Risposta a {chi}. Approvi?\n\n{corpo}"
                 if _it(policy.user_lang()) else
                 f"✍️ Reply to {chi}. Approve?\n\n{corpo}"),
        buttons=tg.action_buttons(rid, policy.user_lang(), approve_allowed(tg)),
        actions=policy.toast_actions(rid))
    return rid


def rifai(w, tg, rid: str, feedback: str) -> bool:
    """Modifica su una risposta nata da Telegram: la bozza si rifa' con la
    stessa istruzione piu' le correzioni. False se la richiesta non e' nata qui."""
    rs = rules_mod.store()
    raw = rs.kv_get(_KV_REQ + str(rid), "")
    if not raw:
        return False
    try:
        dato = json.loads(raw)
    except Exception:
        return False
    rec = policy.store().get(rid)
    if rec and rec["status"] == policy.PENDING and not rec["expired"]:
        policy.store().reject(rid, by=f"telegram:{tg.chat_id}")
    precedente = ((rec or {}).get("args") or {}).get("body")
    rispondi(w, tg, dato["chiave"], dato["istruzione"],
             previous_body=precedente, feedback=feedback)
    return True


# ── confirmation drafted at once ─────────────────────────────────────

def _when(start: str) -> str:
    from gigamail.core import availability
    try:
        return availability.etichetta_slot(datetime.fromisoformat(start))
    except Exception:
        return str(start or "")


def _confirmable(outcome: Dict[str, Any], touched: Optional[Dict[str, Any]]) -> bool:
    """One precise time, free in the calendar: either the client accepted
    a time we offered (already in the calendar) or asked for a new one
    that is free."""
    state = outcome.get("stato")
    if state == "confermato":
        return bool(touched) and not touched.get("invariato") and not outcome.get("arreso")
    if state != "proposto" or not outcome.get("scelta_unica"):
        return False
    if outcome.get("occupato") or outcome.get("agenda_illeggibile"):
        return False
    from gigamail.core import appointments
    return appointments.libero(outcome["inizio"], outcome["fine"]) is True


def draft_confirmation(w, tg, account_id: int, row: Dict[str, Any],
                       message: Dict[str, Any], outcome: Dict[str, Any],
                       touched: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """The client named one free time: draft the confirmation now and send
    it for approval, instead of waiting for the user to ask for it.
    Returns the request id, or None when nothing was drafted."""
    if not _confirmable(outcome, touched):
        return None
    mid = str(message.get("id") or "")
    if mid and rules_mod.store().get_handled(RULE_ID, mid):
        return None                      # already drafted for this mail
    where = "by video call" if row.get("video") else "at our office"
    instruction = (f"Confirm the appointment for {_when(outcome['inizio'])} "
                   f"{where}: that time is free in the calendar. Thank them "
                   "and say we look forward to meeting them. Do not propose "
                   "other times.")
    key = register_context(account_id, message)
    return rispondi(w, tg or DesktopChannel(), key, instruction, announce=False)


# ── replies and edits queued from the desktop ────────────────────────

def _queue(entry: Dict[str, Any]) -> None:
    name = f"{_KV_DESKTOP}{time.time():017.6f}_{secrets.token_hex(2)}"
    rules_mod.store().kv_set(name, json.dumps(entry, ensure_ascii=False))


def queue_desktop_reply(key: str, instruction: str) -> bool:
    """Reply button on the desktop alert: the watcher drafts it on its
    next tick. False when the alert is unknown or the text is empty."""
    if not contesto(key) or not (instruction or "").strip():
        return False
    _queue({"key": key, "instruction": instruction.strip()})
    return True


def queue_desktop_edit(request_id: str, feedback: str) -> bool:
    """Edit from the desktop on a reply drafted here: the request is
    already revoked; the watcher redrafts it with the note. False when the
    request was not drafted here."""
    if not rules_mod.store().kv_get(_KV_REQ + str(request_id), ""):
        return False
    _queue({"request_id": request_id, "feedback": feedback})
    return True


def process_desktop_queue(w, tg) -> int:
    """Draft what the desktop queued. Returns how many entries it took."""
    rs = rules_mod.store()
    done = 0
    for name in rs.kv_keys(_KV_DESKTOP):
        raw = rs.kv_get(name, "")
        if not rs.kv_delete(name):
            continue                     # another reader took it
        try:
            entry = json.loads(raw)
        except Exception:
            continue
        channel = tg or DesktopChannel()
        if entry.get("request_id"):
            rifai(w, channel, entry["request_id"], entry.get("feedback") or "")
        else:
            rispondi(w, channel, entry.get("key") or "", entry.get("instruction") or "")
        done += 1
    return done
