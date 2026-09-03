"""Telegram: tap e comandi dall'umano, e il long-poll tra un tick e l'altro.

SOLO la chat configurata conta, e l'approvazione vale solo se quella chat
e' la stessa registrata dietro Hello (kv tg_trusted_chat). Tutto il resto
finisce nell'audit e basta.
"""
import re
import time
from typing import Any, Dict

from ade_mail_agent import policy
from ade_mail_agent.core import approval_pin, telegram_channel
from ade_mail_agent.core import rules as rules_mod

from .log import _log, logger

_PIN_MAX_FAILS = 3
_PIN_LOCK_SECONDS = 900


def say(tg, it: str, en: str) -> None:
    tg.send(it if policy.user_lang() == "it" else en)


def approve_allowed(tg) -> bool:
    """L'approvazione da Telegram vale solo se il chat_id configurato
    in notify.json COINCIDE con quello registrato dietro Hello al
    `telegram setup --approve` (kv tg_trusted_chat). Cambiare il file
    non basta: la fiducia si ri-conquista dal percorso verificato.
    (Hardening da u/Secondmindsystems su r/mcp, 27/08/2026.)"""
    if not tg.approve_enabled:
        return False
    trusted = rules_mod.store().kv_get("tg_trusted_chat", "")
    return trusted == str(tg.chat_id)


def check_trust(tg) -> None:
    """Se la chat configurata e' cambiata rispetto a quella fidata:
    revoca le pending del watcher, avvisa la VECCHIA chat fidata,
    scrivi l'audit. Una volta per cambio (kv tg_mismatch_alerted)."""
    rs = rules_mod.store()
    trusted = rs.kv_get("tg_trusted_chat", "")
    if not tg.approve_enabled or not trusted or trusted == str(tg.chat_id):
        return
    if rs.kv_get("tg_mismatch_alerted", "") == str(tg.chat_id):
        return
    rs.kv_set("tg_mismatch_alerted", str(tg.chat_id))
    policy.audit("telegram", {"configured": tg.chat_id,
                              "trusted": trusted},
                 "telegram_chat_mismatch")
    revoked = 0
    for row in rs.pending_requests():
        rec = policy.store().get(row["request_id"])
        if rec and rec["status"] == policy.PENDING:
            policy.store().reject(row["request_id"],
                                  by="system:telegram-chat-changed")
            rs.set_status(row["rule_id"], row["message_id"], "rejected",
                          "telegram-chat-changed")
            revoked += 1
    try:
        if policy.user_lang() == "it":
            tg.send_to(int(trusted),
                       f"⚠️ GigaMail: il chat_id configurato e' cambiato "
                       f"({trusted} → {tg.chat_id}). Approvazione da "
                       f"Telegram DISABILITATA e {revoked} richieste in "
                       f"attesa revocate. Se sei stato tu, rifai "
                       f"`gigamail telegram setup --approve` (Hello).")
        else:
            tg.send_to(int(trusted),
                       f"⚠️ GigaMail: the configured chat_id changed "
                       f"({trusted} → {tg.chat_id}). Approval from "
                       f"Telegram DISABLED and {revoked} pending requests "
                       f"revoked. If this was you, re-run "
                       f"`gigamail telegram setup --approve` (Hello).")
    except Exception as e:
        # L'avviso alla vecchia chat e' best-effort (la revoca e l'audit
        # sono gia' fatti), ma non deve sparire senza traccia.
        logger.warning("avviso cambio chat Telegram non consegnato a %s: %s", trusted, e)


def handle_event(w, tg, ev: Dict[str, Any]) -> None:
    """Un update di Telegram. SOLO la chat configurata conta: il resto
    finisce nell'audit e basta."""
    if not tg.is_trusted(ev):
        policy.audit("telegram", {"chat_id": ev.get("chat_id"),
                                  "from_id": ev.get("from_id")},
                     "telegram_unauthorized")
        return
    rs = rules_mod.store()
    if ev["kind"] == "callback":
        m = re.match(r"^([arm]):(req_[0-9a-f]+)$", ev.get("data", ""))
        tg.answer_callback(ev.get("callback_id", ""))
        if m:
            action(w, tg, m.group(1), m.group(2), rs,
                   message_id=ev.get("message_id", 0))
        return
    text = (ev.get("text") or "").strip()
    in_attesa_pin = rs.kv_get("tg_await_pin", "")
    if in_attesa_pin:
        check_pin(w, tg, in_attesa_pin, text, rs, ev.get("message_id", 0))
        return
    waiting = rs.kv_get("tg_await_feedback")
    if waiting:
        rs.kv_set("tg_await_feedback", "")
        retry(w, tg, waiting, text, rs)
        return
    m = re.match(r"^/?(approva|approve|si|sì|ok|yes)\s+(req_[0-9a-f]+)\s*$",
                 text, re.I)
    if m:
        action(w, tg, "a", m.group(2), rs)
        return
    m = re.match(r"^/?(rifiuta|reject|no)\s+(req_[0-9a-f]+)\s*(?::\s*(.+))?$",
                 text, re.I | re.S)
    if m:
        if m.group(3):
            retry(w, tg, m.group(2), m.group(3).strip(), rs)
        else:
            action(w, tg, "r", m.group(2), rs)
        return
    say(tg,
        "Comandi: 'approva req_x', 'rifiuta req_x', "
        "'rifiuta req_x: <modifiche>' — o i bottoni sotto la bozza.",
        "Commands: 'approve req_x', 'reject req_x', "
        "'reject req_x: <changes>' — or the buttons under the draft.")


def action(w, tg, act: str, rid: str, rs, message_id: int = 0) -> None:
    row = rs.find_by_request(rid)
    rec = policy.store().get(rid)
    if not rec:
        say(tg, f"{rid}: richiesta sconosciuta.", f"{rid}: unknown request.")
        return
    # `row` esiste solo per le bozze nate da una regola. Una
    # richiesta creata da un tool (send_mail dell'agente) non ne
    # ha una, e prima finiva qui come 'sconosciuta': i bottoni
    # c'erano ma non facevano niente.
    da_regola = bool(row)
    if rec["expired"] and rec["status"] == policy.PENDING:
        # Scaduta e mai decisa: dire "gia' decisa" mostrando
        # "pending" e' una contraddizione che lascia l'umano a
        # chiedersi cosa sia successo. Qui non c'e' niente da
        # decidere: la richiesta e' morta di vecchiaia e va rifatta.
        quando = time.strftime("%H:%M", time.localtime(rec["expires_at"]))
        say(tg,
            f"⏱ {rid}: scaduta alle {quando}, nessuno l'ha "
            "decisa. Niente e' partito. Chiedi all'agente di "
            "rifare la richiesta.",
            f"⏱ {rid}: expired at {quando}, nobody decided "
            "it. Nothing was sent. Ask the agent to raise it "
            "again.")
        tg.clear_buttons(message_id)
        return
    if rec["status"] == policy.APPROVED and act == "r":
        # Approvata ma non ancora eseguita: il rifiuto qui vale
        # come REVOCA. E' il caso piu' frequente in assoluto — si
        # approva e un secondo dopo ci si accorge dell'errore — e
        # prima l'unica difesa era aspettare la scadenza con la
        # richiesta eseguibile per tutta la finestra.
        ok = policy.store().revoke(rid, by=f"telegram:{tg.chat_id}")
        if da_regola and ok:
            rs.set_status(row["rule_id"], row["message_id"], "rejected")
        say(tg,
            f"↩ Approvazione revocata ({rid}). Non e' partita."
            if ok else f"{rid}: troppo tardi, e' gia' stata eseguita.",
            f"↩ Approval revoked ({rid}). Nothing was sent."
            if ok else f"{rid}: too late, it has been executed.")
        tg.clear_buttons(message_id)
        return
    if rec["status"] != policy.PENDING:
        say(tg,
            f"{rid}: gia' decisa ({rec['status']}). Nessuna azione.",
            f"{rid}: already decided ({rec['status']}). No action.")
        tg.clear_buttons(message_id)
        return
    who = f"telegram:{tg.chat_id}"
    if act == "a":
        if not approve_allowed(tg):
            say(tg,
                "L'approvazione da Telegram non e' abilitata su "
                "questo GigaMail: approva dal PC (Hello). Da qui "
                "puoi solo rifiutare o chiedere modifiche.",
                "Approval from Telegram is not enabled on this "
                "GigaMail: approve on the PC (Hello). From here "
                "you can only reject or ask for changes.")
            return
        atteso = rs.kv_get("tg_approve_pin", "")
        if atteso:
            # Con un PIN configurato il tap non decide: apre solo la
            # domanda. Avere il telefono non basta piu', bisogna
            # anche sapere il PIN.
            bloccato = pin_locked(rs)
            if bloccato:
                say(tg,
                    "\U0001F512 Approvazione da Telegram bloccata per "
                    f"{bloccato}s dopo troppi PIN sbagliati. Approva dal PC.",
                    "\U0001F512 Telegram approval locked for "
                    f"{bloccato}s after too many wrong PINs. Approve from the PC.")
                return
            rs.kv_set("tg_await_pin", rid)
            say(tg,
                f"\U0001F511 Scrivi il PIN per approvare {rid}.",
                f"\U0001F511 Type the PIN to approve {rid}.")
            return
        if not policy.store().approve(rid, by=who):
            say(tg, f"{rid}: non approvabile.", f"{rid}: not approvable.")
            return
        if not da_regola:
            # Nessuno qui puo' eseguirla: la fase 2 di un tool la
            # completa l'agente che l'ha chiesta. Dirlo, invece di
            # far credere che sia partita.
            say(tg,
                f"✅ Approvata ({rid}). Non e' ancora partita: "
                "la completa l'agente che l'ha richiesta.",
                f"✅ Approved ({rid}). Not sent yet: the agent "
                "that asked for it completes the send.")
            tg.clear_buttons(message_id)
            return
        w.execute_approved()
        h = rs.get_handled(row["rule_id"], row["message_id"]) or {}
        ok = h.get("status") == "sent"
        say(tg,
            f"✅ Inviata ({rid})." if ok
            else f"⚠️ Approvata ma invio fallito ({rid}): {h.get('reason')}",
            f"✅ Sent ({rid})." if ok
            else f"⚠️ Approved but send failed ({rid}): {h.get('reason')}")
        tg.clear_buttons(message_id)
        return
    if act == "r":
        policy.store().reject(rid, by=who)
        if da_regola:
            rs.set_status(row["rule_id"], row["message_id"], "rejected")
        say(tg, f"❌ Rifiutata ({rid}). Nessun invio.",
            f"❌ Rejected ({rid}). Nothing sent.")
        tg.clear_buttons(message_id)
        return
    if act == "m":
        rs.kv_set("tg_await_feedback", rid)
        if not da_regola:
            say(tg,
                f"✏️ Scrivi qui cosa vuoi cambiare in {rid}: "
                "annullo questa richiesta e riporto la nota "
                "all'agente.",
                f"✏️ Type what to change in {rid}: I will cancel "
                "this request and pass your note to the agent.")
            return
        say(tg,
            f"✏️ Scrivi qui le modifiche che vuoi alla bozza {rid}: "
            "la rifaccio e te la ripropongo.",
            f"✏️ Type the changes you want to draft {rid}: "
            "I will redo it and propose it again.")


def pin_locked(rs) -> int:
    """Secondi di blocco rimanenti, 0 se libero."""
    fino = float(rs.kv_get("tg_pin_locked_until", "0") or 0)
    resta = int(fino - time.time())
    return resta if resta > 0 else 0


def check_pin(w, tg, rid: str, text: str, rs, message_id: int = 0) -> None:
    """Il PIN scritto in chat.

    Il messaggio viene cancellato SUBITO, giusto o sbagliato che
    sia: un PIN lasciato nella cronologia lo legge chiunque riapra
    la conversazione, e la cancellazione non deve dipendere
    dall'esito."""
    tg.delete_message(message_id)
    rs.kv_set("tg_await_pin", "")
    rec = policy.store().get(rid)
    if not rec or rec["status"] != policy.PENDING or rec["expired"]:
        say(tg,
            f"{rid}: non piu' approvabile. Niente e' partito.",
            f"{rid}: no longer approvable. Nothing sent.")
        return
    if not approval_pin.verify_pin(text, rs.kv_get("tg_approve_pin", "")):
        falliti = int(rs.kv_get("tg_pin_fails", "0") or 0) + 1
        rs.kv_set("tg_pin_fails", str(falliti))
        policy.audit("telegram", {"request_id": rid}, "pin_failed",
                     detail=f"tentativo {falliti}")
        if falliti >= _PIN_MAX_FAILS:
            rs.kv_set("tg_pin_fails", "0")
            rs.kv_set("tg_pin_locked_until",
                      str(time.time() + _PIN_LOCK_SECONDS))
            policy.audit("telegram", {"request_id": rid}, "pin_locked")
            say(tg,
                "\U0001F512 Tre PIN sbagliati: approvazione da Telegram "
                "bloccata per 15 minuti. Se non sei stato tu, qualcuno "
                "ha in mano il tuo Telegram.",
                "\U0001F512 Three wrong PINs: Telegram approval locked "
                "for 15 minutes. If this was not you, someone has your "
                "Telegram.")
            return
        resta = _PIN_MAX_FAILS - falliti
        say(tg,
            f"❌ PIN errato. Altri {resta} tentativi. Ritenta "
            f"premendo Approva su {rid}.",
            f"❌ Wrong PIN. {resta} attempts left. Tap Approve "
            f"on {rid} to retry.")
        return
    rs.kv_set("tg_pin_fails", "0")
    who = f"telegram:{tg.chat_id}+pin"
    if not policy.store().approve(rid, by=who):
        say(tg, f"{rid}: non approvabile.", f"{rid}: not approvable.")
        return
    row = rs.find_by_request(rid)
    if not row:
        say(tg,
            f"✅ Approvata ({rid}). Non e' ancora partita: la "
            "completa l'agente che l'ha richiesta.",
            f"✅ Approved ({rid}). Not sent yet: the agent that "
            "asked for it completes the send.")
        return
    w.execute_approved()
    h = rs.get_handled(row["rule_id"], row["message_id"]) or {}
    ok = h.get("status") == "sent"
    say(tg,
        f"✅ Inviata ({rid})." if ok
        else f"⚠ Approvata ma invio fallito ({rid}).",
        f"✅ Sent ({rid})." if ok
        else f"⚠ Approved but send failed ({rid}).")


def retry(w, tg, rid: str, feedback: str, rs) -> None:
    row = rs.find_by_request(rid)
    rec = policy.store().get(rid)
    if not rec:
        say(tg, f"{rid}: richiesta sconosciuta.", f"{rid}: unknown request.")
        return
    if not row:
        # Richiesta di un tool: non c'e' nessuna bozza da rifare
        # qui. La si annulla e la nota resta nell'audit, da
        # riportare all'agente — come fa il bottone Modifica sul PC.
        if rec["status"] == policy.PENDING and not rec["expired"]:
            policy.store().reject(
                rid, by=f"telegram:{tg.chat_id} modifica: {feedback[:200]}")
        policy.audit("approval", {"request_id": rid}, "edit_requested",
                     detail=feedback[:200])
        say(tg,
            f"✏️ Annullata ({rid}). Nota registrata: {feedback[:200]}",
            f"✏️ Cancelled ({rid}). Note recorded: {feedback[:200]}")
        return
    if not feedback:
        say(tg, "Modifiche vuote: nessuna azione.", "Empty changes: nothing done.")
        return
    if rec["status"] == policy.PENDING and not rec["expired"]:
        policy.store().reject(rid, by=f"telegram:{tg.chat_id}")
    rs.request_retry(row["rule_id"], row["message_id"], feedback)
    policy.audit("watch_rule", {"rule_id": row["rule_id"],
                                "message_id": row["message_id"]},
                 "retry_requested", detail=feedback[:200])
    say(tg, "✏️ Ok, rifaccio la bozza con le tue modifiche…",
        "✏️ Ok, redoing the draft with your changes…")
    w.process_retries()


def wait(w, seconds: int) -> None:
    """Tra un tick e l'altro: long-poll di Telegram se configurato
    (reagisce subito a un tap), altrimenti sleep."""
    tg = telegram_channel.channel()
    if not tg:
        time.sleep(seconds)
        return
    check_trust(tg)
    rs = rules_mod.store()
    deadline = time.time() + seconds
    while True:
        remaining = int(deadline - time.time())
        if remaining <= 0:
            return
        offset = int(rs.kv_get("tg_offset", "0") or 0)
        events, new_offset = tg.poll(offset, timeout=min(remaining, 30))
        if new_offset != offset:
            rs.kv_set("tg_offset", str(new_offset))
        for ev in events:
            try:
                handle_event(w, tg, ev)
            except Exception as e:
                _log(f"telegram event fallito: {e}", True)
        if events:
            return  # qualcosa e' successo: tick subito
