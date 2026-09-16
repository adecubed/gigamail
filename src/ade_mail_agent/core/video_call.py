# GigaMail — mail for your AI agent
# Copyright (C) 2026 Adecubed
# Licensed under the GNU AGPL v3 or later. See LICENSE.
"""Video call: dall'appuntamento confermato al link, dietro approvazione.

Quando una conversazione parla di video call e l'orario viene confermato,
qui si crea la riunione Zoom, si mette il link nell'evento di calendario e
si prepara la mail con il link. La mail NON parte da sola: diventa una
richiesta di approvazione come le bozze delle regole, e il watcher la
spedisce solo dopo il si' dell'umano.

Prima il link lo creava a mano l'utente, dopo aver letto la conferma del
cliente, e lo spediva con un altro giro di richieste. Un passaggio in piu'
per ogni cliente, e il piu' facile da dimenticare.
"""
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from ade_mail_agent import policy

from . import (
    accounts,
    appointments,
    availability,
    calendar_router,
    telegram_channel,
    zoom,
)
from . import rules as rules_mod

logger = logging.getLogger("gigamail.video_call")

# Le richieste nate qui si registrano nella tabella delle regole con questo
# rule_id: e' cosi' che il watcher le trova ed esegue dopo l'approvazione.
RULE_ID = "appuntamenti-video"
_TTL_SECONDI = 4 * 3600
# Riunione "personale": non nasce da Zoom, e' il link fisso dell'utente. Si
# riconosce da qui, perche' non si sposta e non si cancella come le altre.
_FISSO = "personale"


def link_fisso() -> str:
    """Il link personale Zoom dell'utente, se lo ha salvato.

    Serve a chi non vuole creare un'app Server-to-Server: si incolla una
    volta e vale per tutte le video call. In cambio e' sempre lo stesso
    link, quindi conviene tenere la sala d'attesa accesa."""
    return str(accounts.get_setting("zoom_link_fisso", "") or "").strip()


def e_video(testo: str) -> bool:
    return appointments.parla_di_video(testo)


def _minuti(esito: Dict[str, Any]) -> int:
    try:
        inizio = datetime.fromisoformat(esito["inizio"])
        fine = datetime.fromisoformat(esito["fine"])
        return max(15, int((fine - inizio).total_seconds() // 60))
    except Exception:
        return 60


def _nome(messaggio: Dict[str, Any]) -> str:
    f = (messaggio or {}).get("from") or {}
    ea = f.get("emailAddress") if isinstance(f, dict) else None
    return str(ea.get("name") or "").strip() if isinstance(ea, dict) else ""


def _oggetto_risposta(subject: str) -> str:
    testo = re.sub(r"\s+", " ", str(subject or "")).strip()
    return testo if testo.lower().startswith("re:") else f"Re: {testo}"


def _cc(account_id: int) -> List[str]:
    """Le stesse copie delle regole di quell'account: chi mette sempre in
    copia un indirizzo lo vuole anche sulla mail con il link."""
    visti: List[str] = []
    for regola in rules_mod.store().list_all():
        if int(regola.get("account_id") or 0) != int(account_id):
            continue
        for indirizzo in regola.get("cc") or []:
            if indirizzo and indirizzo.lower() not in (v.lower() for v in visti):
                visti.append(indirizzo)
    return visti


def _firma(account_id: int) -> str:
    return str(accounts.get_setting(f"firma_account_{int(account_id)}", "")
               or "").strip()


def testo_mail(nome: str, quando: str, url: str, password: str,
               firma: str) -> str:
    righe = [f"Gentile {nome}," if nome else "Buongiorno,", "",
             f"le confermo la video call su Zoom per {quando}.", "",
             "Per collegarsi basta aprire questo link all'orario indicato:",
             url]
    if password:
        righe.append(f"Codice d'accesso: {password}")
    righe += ["", "Cordiali saluti,"]
    if firma:
        righe.append(firma)
    return "\n".join(righe) + "\n"


def _pulsanti(request_id: str):
    tg = telegram_channel.channel()
    if not tg:
        return None
    fidata = rules_mod.store().kv_get("tg_trusted_chat", "")
    puo_approvare = bool(tg.approve_enabled) and fidata == str(tg.chat_id)
    return tg.action_buttons(request_id, policy.user_lang(), puo_approvare)


def _nel_calendario(event_id: str, url: str) -> None:
    if not (event_id and url):
        return
    try:
        calendar_router.update_event(
            event_id, location=url, body=f"Video call Zoom: {url}")
    except Exception as e:
        logger.warning("link Zoom non scritto nell'evento %s: %s", event_id, e)


def dopo_conferma(account_id: int, riga: Dict[str, Any],
                  messaggio: Dict[str, Any], mittente: str, subject: str,
                  esito: Dict[str, Any],
                  toccato: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Riunione, link in calendario, mail in approvazione.

    Ritorna cosa e' successo, per l'avviso all'umano:
      creata          riunione nuova e mail con il link in approvazione
      spostata        l'appuntamento aveva gia' una riunione: cambia l'ora,
                      il link resta quello gia' spedito
      non_configurato Zoom non collegato, il link va mandato a mano
    Gli errori di Zoom salgono al chiamante, che li riporta nell'avviso."""
    chiave = riga["thread_key"]
    fisso = link_fisso()
    if not zoom.configurato() and not fisso:
        return {"stato": "non_configurato"}
    st = appointments.store()
    corrente = st.get(account_id, chiave) or {}
    durata = _minuti(esito)
    event_id = str((toccato or {}).get("event_id")
                   or corrente.get("event_id") or "")

    if corrente.get("zoom_id"):
        # Il link personale non si sposta: e' sempre lo stesso, e il
        # cliente ce l'ha gia'. Cambia solo l'orario dell'appuntamento.
        if corrente["zoom_id"] != _FISSO:
            zoom.sposta_riunione(corrente["zoom_id"], esito["inizio"], durata)
        _nel_calendario(event_id, corrente.get("zoom_url") or "")
        policy.audit("appointment", {"account_id": account_id,
                                     "thread": chiave}, "zoom_moved")
        return {"stato": "spostata", "join_url": corrente.get("zoom_url") or "",
                "fisso": corrente["zoom_id"] == _FISSO}

    nome = _nome(messaggio)
    if fisso and not zoom.configurato():
        riunione = {"id": _FISSO, "join_url": fisso, "password": ""}
    else:
        riunione = zoom.crea_riunione(
            f"Video call con {nome or corrente.get('con') or mittente}",
            esito["inizio"], durata,
            agenda=re.sub(r"\s+", " ", str(subject or ""))[:300])
    st.set_zoom(account_id, chiave, riunione["id"], riunione["join_url"])
    _nel_calendario(event_id, riunione["join_url"])
    policy.audit("appointment", {"account_id": account_id, "thread": chiave},
                 "zoom_created")

    quando = availability.etichetta_slot(datetime.fromisoformat(esito["inizio"]))
    corpo = testo_mail(nome, quando, riunione["join_url"],
                       riunione["password"], _firma(account_id))
    cc = _cc(account_id)
    message_id = str((messaggio or {}).get("id") or f"zoom-{riunione['id']}")
    args = {"to": mittente, "subject": _oggetto_risposta(subject),
            "body": corpo, "account_id": int(account_id), "cc": cc,
            "message_id": message_id}
    mittente_nostro = (accounts.get_account_by_id(int(account_id)) or {})
    preview = {"from": mittente_nostro.get("email"), "to": mittente, "cc": cc,
               "bcc": [], **policy.describe_recipients(mittente, cc, None),
               "subject": args["subject"], "body": corpo}
    request_id = policy.store().create("reply_mail", args, preview,
                                       ttl=_TTL_SECONDI)
    policy.audit("reply_mail", {"to": mittente, "account_id": account_id},
                 "approval_requested", detail="video_call")
    rules_mod.store().record(RULE_ID, account_id, message_id, mittente,
                             "awaiting_approval", "", request_id)
    policy.notify_approval_requested(
        request_id, "reply_mail", preview,
        message=(f"🎥 Link Zoom per {nome or mittente}, {quando}. "
                 f"Approvi la mail?\n\n{corpo}"),
        buttons=_pulsanti(request_id),
        actions=policy.toast_actions(request_id))
    return {"stato": "creata", "join_url": riunione["join_url"],
            "request_id": request_id, "fisso": riunione["id"] == _FISSO}
