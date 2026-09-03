"""Cio' che prima faceva l'LLM interno ora lo fa l'agente dell'utente: bozze, domande, riassunti. Piu' observer."""
import json
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ade_mail_agent import agent_bridge
from ade_mail_agent.core import accounts as core_accounts
from ade_mail_agent.core import (
    availability,
    identity_reader,
    mail_memory,
    mail_router,
    ms_calendar,
    observer,
)

from .common import _active_id

router = APIRouter()


# ── AGENTE (cio' che prima faceva l'LLM interno ora lo fa l'agente) ──

def _identity_context(aid: Optional[int]) -> str:
    if not aid:
        return ""
    ident = core_accounts.get_identity(aid)
    parts = []
    if ident.get("who_am_i"):
        parts.append(f"Chi sono: {ident['who_am_i']}")
    if ident.get("what_i_do"):
        parts.append(f"Cosa faccio: {ident['what_i_do']}")
    if ident.get("tone"):
        parts.append(f"Tono richiesto: {ident['tone']}")
    if ident.get("key_info"):
        parts.append(f"Info chiave: {ident['key_info']}")
    return "\n".join(parts)


def _run_agent(prompt: str) -> dict:
    try:
        return {"draft": agent_bridge.run(prompt), "engine": "agent"}
    except agent_bridge.AgentUnavailable as e:
        raise HTTPException(503, str(e)) from e


_APPUNTAMENTO_KW = (
    "appuntament", "visita", "visitare", "vedere l", "sopralluogo", "incontr",
    "disponibil", "quando poss", "fissare", "calendario", "vederci",
)


def _slots_context(text: str, max_slots: int = 3) -> str:
    """Se il testo parla di appuntamenti, calcola gli slot liberi e li mette
    nel prompt: l'agente propone orari VERI, non inventati."""
    low = (text or "").lower()
    if not any(k in low for k in _APPUNTAMENTO_KW):
        return ""
    try:
        events = ms_calendar.get_events(days_ahead=8)
        slots = availability.find_free_slots(events, days_ahead=7,
                                             max_slots=max_slots)
    except Exception:
        return ""
    if not slots:
        return ""
    righe = "; ".join(s["label"] for s in slots)
    return ("\nDISPONIBILITA' REALE dal calendario (proponi SOLO questi "
            f"orari, senza inventarne altri): {righe}")


def _suggest_attachments(aid: Optional[int], text: str) -> list:
    """Propone allegati dai file di conoscenza dell'account in base al testo
    dell'istruzione/oggetto (es. 'manda la planimetria A.2.1'). La UI mostra
    i suggerimenti con checkbox: decide sempre l'utente."""
    if not aid or not (text or "").strip():
        return []
    try:
        ident = core_accounts.get_identity(aid)
        paths = ident.get("file_paths") or []
        if not paths:
            return []
        hits = identity_reader.find_relevant_files(paths, text, max_files=5)
        return [{"name": h["name"], "path": h["path"]} for h in hits]
    except Exception:
        return []


@router.get("/agent/status")
def agent_status():
    return agent_bridge.status()


class GenerateDraftRequest(BaseModel):
    instruction: str
    to: str = ""
    subject: str = ""


@router.post("/mail/generate_draft")
def generate_draft(req: GenerateDraftRequest, account_id: Optional[int] = None):
    aid = account_id or _active_id()
    prompt = (
        "Scrivi il TESTO di una email in italiano (solo il corpo, niente oggetto, "
        "nessun commento) seguendo l'istruzione dell'utente.\n"
        f"{_identity_context(aid)}\n"
        f"Destinatario: {req.to or 'non specificato'}\n"
        f"Oggetto: {req.subject or 'non specificato'}\n"
        f"{_slots_context(req.instruction + ' ' + req.subject)}\n"
        f"Istruzione: {req.instruction}"
    )
    out = _run_agent(prompt)
    # Gli allegati seguono ciò che l'agente ha SCRITTO (può aver cambiato
    # riferimento: es. immobile richiesto non disponibile -> ne propone un
    # altro), non solo l'istruzione iniziale.
    out["suggested_attachments"] = _suggest_attachments(
        aid, f"{out.get('draft', '')} {req.instruction} {req.subject}"
    )
    return out


class SmartDraftRequest(BaseModel):
    instruction: str = ""
    body_text: str = ""
    subject: str = ""
    sender: str = ""


@router.post("/mail/{message_id}/smart_draft")
def smart_draft(message_id: str, req: SmartDraftRequest,
                account_id: Optional[int] = None, folder: str = ""):
    aid = account_id or _active_id()
    body = req.body_text
    if not body:
        try:
            msg = mail_router.get_message(aid, message_id=message_id, folder=folder) or {}
            body = (msg.get("body", {}) or {}).get("content") or msg.get("bodyPreview") or ""
            req.subject = req.subject or msg.get("subject") or ""
        except Exception:
            pass
    obs = ""
    try:
        obs = observer.get_context_for_prompt(aid or 0, sender=req.sender, subject=req.subject)
    except Exception:
        pass
    prompt = (
        "Scrivi la RISPOSTA a questa email in italiano (solo il corpo, nessun "
        "commento). Rispetta il tono e le correzioni abituali dell'utente.\n"
        f"{_identity_context(aid)}\n"
        f"{obs}\n"
        f"Mittente: {req.sender}\nOggetto: {req.subject}\n"
        f"--- EMAIL RICEVUTA ---\n{body[:6000]}\n--- FINE EMAIL ---\n"
        f"{_slots_context(req.instruction + ' ' + req.subject + ' ' + body[:2000])}\n"
        f"Istruzione dell'utente: {req.instruction or 'rispondi in modo appropriato'}"
    )
    out = _run_agent(prompt)
    out["suggested_attachments"] = _suggest_attachments(
        aid, f"{out.get('draft', '')} {req.instruction} {req.subject} {body[:1000]}"
    )
    return out


class MailAskRequest(BaseModel):
    question: str
    account_id: Optional[int] = None


@router.post("/mail_ask")
def mail_ask(req: MailAskRequest):
    """La domanda va all'agente, che usa i suoi tool MCP ade-mail per
    cercare e leggere la posta prima di rispondere."""
    prompt = (
        "Domanda dell'utente sulla sua posta (usa i tool ade-mail per cercare "
        "e leggere le mail rilevanti prima di rispondere; rispondi in "
        f"italiano, conciso): {req.question}"
    )
    try:
        return {"answer": agent_bridge.run(prompt), "engine": "agent"}
    except agent_bridge.AgentUnavailable as e:
        raise HTTPException(503, str(e)) from e


class SenderSummaryRequest(BaseModel):
    sender: str
    account_id: Optional[int] = None


@router.post("/mail/sender_summary")
def sender_summary(req: SenderSummaryRequest):
    profile = mail_memory.get_sender_profile(req.sender) or {}
    prompt = (
        f"Riassumi in 3-4 frasi il rapporto con questo mittente ({req.sender}) "
        "usando i tool ade-mail (sender_history, search_mail) per recuperare "
        f"lo storico. Profilo noto: {json.dumps(profile, ensure_ascii=False)[:800]}"
    )
    try:
        return {"summary": agent_bridge.run(prompt), "engine": "agent"}
    except agent_bridge.AgentUnavailable as e:
        raise HTTPException(503, str(e)) from e


# ── OBSERVER + AUDIT ─────────────────────────────────────────────────

@router.get("/observer/stats")
def observer_stats(account_id: Optional[int] = None):
    aid = account_id or _active_id() or 0
    return observer.get_stats(aid)
