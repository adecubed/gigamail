"""Approvazioni: il canale fuori banda (Hello / Touch ID) e l'audit."""
import json
import os

from fastapi import APIRouter, HTTPException

from ade_mail_agent import policy

from .common import _who

router = APIRouter()


# ── APPROVAZIONI (il canale fuori banda) ─────────────────────────────
# Questi endpoint sono il punto in cui un UMANO autorizza un'azione
# distruttiva richiesta dall'agente. Vivono qui, dietro il token della
# console, e non esistono come tool MCP: l'agente puo' creare richieste
# e leggerne lo stato, ma non puo' approvarle.

@router.get("/approvals")
def list_approvals():
    """Richieste in attesa di approvazione umana."""
    return policy.store().list_pending()


@router.get("/approvals/{request_id}")
def get_approval(request_id: str):
    rec = policy.store().get(request_id)
    if not rec:
        raise HTTPException(404, "Richiesta inesistente")
    return rec



@router.post("/approvals/{request_id}/approve")
def approve_request(request_id: str):
    """Approva SOLO dopo una verifica dell'utente fisico (Windows Hello /
    Touch ID). Il token di sessione della console sta in un file: un
    processo puo' leggerlo e chiamare questo endpoint. Il prompt OS e'
    cio' che un processo non puo' superare — quindi sta qui, non nella
    finestra. Senza backend di consenso: 503, nessuna approvazione."""
    from ade_mail_agent import consent
    rec = policy.store().get(request_id)
    if not rec:
        raise HTTPException(404, "Richiesta inesistente")
    reason = f"GigaMail: approvare {rec['tool']} ({request_id})?"
    try:
        ok = consent.require_human(reason)
    except consent.ConsentUnavailable as e:
        raise HTTPException(503, str(e)) from e
    if not ok:
        raise HTTPException(403, "Verifica utente non superata o annullata")
    if not policy.store().approve(request_id, by=_who()):
        raise HTTPException(409, "Richiesta non approvabile (già decisa o scaduta)")
    return {"success": True, "request_id": request_id, "status": "approved"}


@router.post("/approvals/{request_id}/reject")
def reject_request(request_id: str):
    if not policy.store().reject(request_id, by=_who()):
        raise HTTPException(409, "Richiesta non rifiutabile (già decisa o scaduta)")
    return {"success": True, "request_id": request_id, "status": "rejected"}


@router.get("/audit")
def audit_log(limit: int = 100):
    """Ultime azioni compiute dall'agente (per la vista console)."""
    from ade_mail_agent.core.data_paths import app_root
    path = os.path.join(str(app_root()), "agent_audit.jsonl")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        lines = f.readlines()[-limit:]
    out = []
    for line in reversed(lines):
        try:
            out.append(json.loads(line))
        except Exception:
            pass
    return out
