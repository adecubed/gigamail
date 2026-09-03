"""Una mail matchata da una regola, dall'inizio alla decisione.

Ordine fisso, fail-closed a ogni passo:
  6. raffica            → la regola si pausa da sola
  5. tetto e cooldown   → skip (non per i retry chiesti dall'umano)
  1,2,3,7. barriere     → mail_guard.check su header + messaggio intero
  modalita' effettiva   → auto solo se regola, DMARC, primo contatto e
                          "non ancora letta" lo permettono; altrimenti semi
  bozza                 → agente dell'utente, SOLO corpo, con retry
  indirizzamento        → From fisso; dal corpo solo se la regola lo chiede
  allegati              → risolti contro l'identita', o si salta
  richiesta             → policy (dedup, cap); semi notifica, auto esegue
"""
import re
import time
from typing import Any, Dict, Optional

from ade_mail_agent import agent_bridge, policy
from ade_mail_agent.core import attachments as attachments_mod
from ade_mail_agent.core import mail_guard, mail_router, telegram_channel
from ade_mail_agent.core import rules as rules_mod

from . import drafting, notify
from .addressing import _reply_subject, body_reply_address
from .approvals import TOOL, _create_request, _execute_reply, _preview_for
from .ingestion import folder_of
from .log import _log, logger
from .telegram import approve_allowed


def process_message(w, rule: Dict[str, Any], message: Dict[str, Any],
                    retry_feedback: Optional[str] = None,
                    previous_body: Optional[str] = None) -> str:
    """Ritorna lo status registrato (per i test e per il log).
    `retry_feedback`: l'umano ha rifiutato una bozza e chiesto una
    modifica — si rifa' la bozza col feedback, si saltano tetto e
    cooldown (l'ha chiesto lui) ma NON le barriere, e l'esito e'
    sempre semi: una bozza corretta a mano la vuole vedere."""
    rs = rules_mod.store()
    rule_id = rule["rule_id"]
    account_id = rule["account_id"]
    message_id = str(message.get("id"))
    sender = mail_guard.sender_address(message)

    def _skip(reason: str) -> str:
        rs.record(rule_id, account_id, message_id, sender, "skipped", reason)
        policy.audit("watch_rule", {"rule_id": rule_id,
                                    "message_id": message_id}, "skipped",
                     detail=reason)
        return "skipped"

    # 6. RAFFICA (fail-closed, prima di tutto): il match si conta
    # comunque, e se il volume in finestra supera la soglia la regola
    # si pausa da sola e riparte solo con Hello.
    rs.record(rule_id, account_id, message_id, sender, "matched")
    n = rs.matches_since(rule_id, time.time() - rules_mod.BURST_WINDOW_SECONDS)
    if n > rules_mod.BURST_MAX:
        window_min = rules_mod.BURST_WINDOW_SECONDS // 60
        reason = (f"raffica: {n} match in {window_min} minuti"
                  if policy.user_lang() == "it"
                  else f"burst: {n} matches in {window_min} minutes")
        rs.pause(rule_id, reason)
        rs.set_status(rule_id, message_id, "skipped", "burst-pause")
        policy.audit("watch_rule", {"rule_id": rule_id}, "rule_paused",
                     detail=reason)
        if policy.user_lang() == "it":
            pause_msg = (f"Regola {rule_id} IN PAUSA da sola: {reason}. "
                         f"Nessun'altra risposta finche' non la riattivi "
                         f"con Hello: gigamail rules resume {rule_id}")
        else:
            pause_msg = (f"Rule {rule_id} PAUSED itself: {reason}. "
                         f"No more replies until you reactivate it with "
                         f"Hello: gigamail rules resume {rule_id}")
        policy.notify_approval_requested(
            "-", f"rule_paused:{rule_id}",
            {"action": "rule autopaused", "reason": reason},
            message=pause_msg)
        return "paused"

    # tetto giornaliero e cooldown per mittente (5) — non per i retry
    # chiesti dall'umano
    if retry_feedback is None:
        if rs.sent_today(rule_id) >= rule["daily_cap"]:
            return _skip("daily-cap")
        last = rs.last_reply_to(rule_id, sender)
        if last and time.time() - last < rule["cooldown_hours"] * 3600:
            return _skip("cooldown")

    # barriere sul messaggio (1,2,3,7) — fail-closed sugli header
    folder = folder_of(rule)
    headers = mail_router.get_message_headers(
        account_id=account_id, message_id=message_id, folder=folder)
    try:
        full = mail_router.get_message(
            account_id=account_id, message_id=message_id, folder=folder) or message
    except Exception as e:
        # Si prosegue con la versione della lista: le barriere girano
        # comunque sugli header, gia' letti sopra.
        logger.debug("messaggio intero %s non letto, uso la lista: %s", message_id, e)
        full = message
    verdict = mail_guard.check(headers, full)
    if not verdict.reply:
        return _skip("guard:" + ",".join(verdict.reasons))

    # modalita' effettiva: auto solo se la regola lo chiede, le barriere
    # lo permettono (DMARC pass) e non e' un primo contatto con
    # first_contact=semi
    mode = rule["mode"]
    if retry_feedback is not None:
        mode = "semi"
    elif mode == "auto":
        if not verdict.auto_ok:
            mode = "semi"
        elif rule["first_contact"] == "semi" and not rs.ever_replied_to(sender, account_id):
            mode = "semi"
        elif bool(full.get("isRead", message.get("isRead"))):
            mode = "semi"  # l'umano l'ha gia' vista: propongo, non invio

    # bozza dall'agente dell'utente, SOLO corpo
    try:
        body = drafting.draft_reply(rule, account_id, full,
                                    feedback=retry_feedback,
                                    previous_body=previous_body)
    except agent_bridge.AgentUnavailable as e:
        # L'agente non ha risposto (timeout, assente): non e' colpa
        # della mail. Si riprova ai giri successivi, fino a
        # _DRAFT_ATTEMPTS; poi si dichiara il fallimento all'umano
        # (misurato dal vivo 22/08: claude -p oltre i 180 s sotto carico).
        prev = rs.get_handled(rule_id, message_id) or {}
        m_att = re.match(r"^draft-attempt:(\d+)$", str(prev.get("reason") or ""))
        attempt = (int(m_att.group(1)) if m_att else 0) + 1
        policy.audit("watch_rule", {"rule_id": rule_id,
                                    "message_id": message_id}, "draft_failed",
                     detail=f"attempt {attempt}: {str(e)[:160]}")
        if attempt < drafting._DRAFT_ATTEMPTS:
            rs.request_retry(rule_id, message_id, retry_feedback or "")
            rs.set_status(rule_id, message_id, "retry", f"draft-attempt:{attempt}")
            return "retry"
        rs.set_status(rule_id, message_id, "failed", f"draft:{e}")
        policy.notify_approval_requested(
            "-", f"draft_failed:{rule_id}", {"action": "draft failed"},
            message=(f"Bozza NON prodotta per la mail da {sender} "
                     f"({rule_id}): l'agente non risponde ({e}). "
                     f"Rispondi a mano."
                     if policy.user_lang() == "it" else
                     f"No draft produced for the mail from {sender} "
                     f"({rule_id}): the agent is not responding ({e}). "
                     f"Reply by hand."))
        return "failed"

    args = {"message_id": message_id, "body": body, "account_id": account_id}
    to_address = None
    if rule.get("reply_to_body_address"):
        to_address = body_reply_address(full, sender)
        if not to_address:
            # La regola promette di scrivere alla persona e la
            # persona non c'e': fermarsi e' l'unica opzione. Il
            # ripiego sul mittente manderebbe la risposta al relay
            # del portale, cioe' proprio cio' che la regola evita.
            rs.set_status(rule_id, message_id, "skipped",
                          "no-body-address")
            policy.audit("watch_rule", {"rule_id": rule_id,
                                        "message_id": message_id},
                         "skipped", detail="no-body-address")
            _log(f"nessun indirizzo nel corpo ({rule_id}, {sender}): "
                 "salto", w.verbose)
            return "skipped"
        args["to"] = to_address
        args["subject"] = _reply_subject(full)
    if rule.get("cc"):
        args["cc"] = list(rule["cc"])
    allegati = []
    if rule.get("attachments"):
        allegati, mancanti = attachments_mod.resolve(
            account_id, rule["attachments"])
        if mancanti:
            # La regola promette allegati che non esistono piu'
            # (file rinominato, identity cambiata): fermarsi e'
            # meglio di una mail che cita planimetrie assenti.
            rs.set_status(rule_id, message_id, "skipped",
                          "attachments-missing")
            policy.audit("watch_rule", {"rule_id": rule_id,
                                        "message_id": message_id},
                         "skipped",
                         detail="allegati non risolti: "
                                + ", ".join(mancanti)[:160])
            _log(f"allegati non risolti ({rule_id}): {mancanti}",
                 w.verbose)
            return "skipped"
        args["attachments"] = allegati
    preview = _preview_for(rule, full, body, mode, to_address,
                           allegati)
    request_id, created = _create_request(rule, args, preview)
    if not request_id:
        rs.set_status(rule_id, message_id, "skipped", "approval-cap")
        return "skipped"

    if mode == "semi":
        rs.record(rule_id, account_id, message_id, sender,
                  "awaiting_approval", "", request_id)
        if created:
            buttons = None
            tg = telegram_channel.channel()
            if tg:
                buttons = tg.action_buttons(
                    request_id, policy.user_lang(), approve_allowed(tg))
            it = policy.user_lang() == "it"
            actions = [("✅ " + ("Approva" if it else "Approve"),
                        f"gigamail://approve/{request_id}"),
                       ("❌ " + ("Rifiuta" if it else "Reject"),
                        f"gigamail://reject/{request_id}")]
            policy.notify_approval_requested(
                request_id, TOOL, preview,
                message=notify._semi_notify_text(rule, full, body, request_id),
                buttons=buttons, actions=actions)
        _log(f"semi: {request_id} in attesa ({rule_id}, {sender})", w.verbose)
        return "awaiting_approval"

    # auto: la richiesta nasce approvata dalla regola, poi si esegue
    # subito con lo stesso percorso consume→execute. L'audit porta
    # automode:<rule_id> e la notifica (B5) parte DOPO, con l'esito
    # vero: "inviata" solo se il provider ha detto si'.
    policy.store().approve(request_id, by=f"automode:{rule_id}")
    try:
        result = _execute_reply(request_id, args)
        ok = bool(result.get("success", True)) if isinstance(result, dict) else bool(result)
    except Exception as e:
        rs.record(rule_id, account_id, message_id, sender, "failed",
                  str(e)[:200], request_id)
        policy.notify_approval_requested(
            request_id, TOOL, preview,
            message=notify._auto_notify_text(rule, full, body, ok=False))
        return "failed"
    rs.record(rule_id, account_id, message_id, sender,
              "sent" if ok else "failed", "" if ok else "send-failed",
              request_id)
    policy.notify_approval_requested(
        request_id, TOOL, preview,
        message=notify._auto_notify_text(rule, full, body, ok))
    _log(f"auto: {'inviata' if ok else 'INVIO FALLITO'} ({rule_id} → {sender})",
         w.verbose)
    return "sent" if ok else "failed"
