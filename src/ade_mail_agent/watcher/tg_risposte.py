"""Rispondere a un cliente da Telegram.

L'avviso "il cliente ha risposto" arrivava su Telegram e li' finiva: per
rispondere bisognava tornare al PC, o chiedere a qualcuno di farlo. Ora
sotto l'avviso c'e' il bottone Rispondi, e si puo' anche rispondere
direttamente al messaggio dell'avviso. Quello che si scrive ("ok, va
bene") e' un'istruzione: la bozza la scrive l'agente, con identity, orari
liberi e presidio anti-injection come le bozze delle regole, e la mail
arriva in approvazione con i soliti bottoni. Niente parte senza un si'.
"""
import json
import secrets
from typing import Any, Dict, List, Optional

from ade_mail_agent import agent_bridge, policy
from ade_mail_agent.core import accounts, mail_router
from ade_mail_agent.core import rules as rules_mod

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


def _it(lang: str) -> bool:
    return (lang or "it") == "it"


def _say(tg, it: str, en: str) -> None:
    tg.send(it if _it(policy.user_lang()) else en)


def bottone(chiave: str, lang: str) -> List[List[Dict[str, str]]]:
    return [[{"text": "✍️ " + ("Rispondi" if _it(lang) else "Reply"),
              "callback_data": f"w:{chiave}"}]]


def registra_avviso(tg, testo: str, account_id: int,
                    messaggio: Dict[str, Any], lang: str) -> str:
    """Manda l'avviso con il bottone Rispondi e ricorda a quale mail si
    riferisce, sia per il bottone sia per chi risponde al messaggio."""
    chiave = secrets.token_hex(4)
    f = messaggio.get("from") or {}
    ea = f.get("emailAddress") if isinstance(f, dict) else None
    ea = ea if isinstance(ea, dict) else {}
    ctx = {"account_id": int(account_id),
           "message_id": str(messaggio.get("id") or ""),
           "folder": "INBOX",
           "mittente": str(ea.get("address") or ""),
           "nome": str(ea.get("name") or "").strip().strip('"').strip(),
           "subject": str(messaggio.get("subject") or "")}
    rs = rules_mod.store()
    rs.kv_set(_KV_CTX + chiave, json.dumps(ctx, ensure_ascii=False))
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
    from ade_mail_agent.core import video_call
    return video_call._cc(account_id)


def rispondi(w, tg, chiave: str, istruzione: str,
             previous_body: Optional[str] = None,
             feedback: Optional[str] = None) -> Optional[str]:
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
