"""Approvazioni: il canale fuori banda (Hello / Touch ID) e l'audit."""
import json
import os
import time

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from gigamail import policy

from .common import _who

router = APIRouter()


# ── APPROVAZIONI (il canale fuori banda) ─────────────────────────────
# Questi endpoint sono il punto in cui un UMANO autorizza un'azione
# distruttiva richiesta dall'agente. Vivono qui, dietro il token della
# console, e non esistono come tool MCP: l'agente puo' creare richieste
# e leggerne lo stato, ma non puo' approvarle.

def _completed_by(request_id: str) -> str:
    """Where a request comes from: "watcher" for a draft born from a rule,
    "agent" for a tool request. Both are sent by GigaMail as soon as they
    are approved; the origin tells the console what to show."""
    from gigamail import completion
    return completion.origin_of(request_id)


def _with_origin(rec):
    rec["completed_by"] = _completed_by(rec["request_id"])
    return rec


def _with_notifications(recs):
    """Each request with the notifications sent for it, and the ones that
    failed: a draft that expired at night with the Telegram send broken
    should say so where the user looks."""
    recs = [_with_origin(r) for r in recs]
    try:
        seen = policy.notifications_of([r["request_id"] for r in recs])
    except Exception:
        seen = {}
    for r in recs:
        r["notified"] = seen.get(r["request_id"], [])
    return recs


@router.get("/approvals")
def list_approvals():
    """Richieste in attesa di approvazione umana."""
    return _with_notifications(policy.store().list_pending())


@router.get("/approvals/recent")
def recent_approvals(hours: float = 24):
    """Requests decided (or expired undecided) in the last `hours`: the
    console's "recently decided" list, with the execution outcome."""
    hours = max(0.0, min(float(hours), 24 * 30))
    since = time.time() - hours * 3600
    return _with_notifications(policy.store().list_decided(since))


@router.get("/approvals/{request_id}")
def get_approval(request_id: str):
    rec = policy.store().get(request_id)
    if not rec:
        raise HTTPException(404, "Richiesta inesistente")
    return rec



@router.post("/approvals/{request_id}/approve")
def approve_request(request_id: str, request: Request = None):
    """Approva SOLO dopo una verifica dell'utente fisico (Windows Hello /
    Touch ID). Il token di sessione della console sta in un file: un
    processo puo' leggerlo e chiamare questo endpoint. Il prompt OS e'
    cio' che un processo non puo' superare — quindi sta qui, non nella
    finestra. Senza backend di consenso: 503, nessuna approvazione.

    Un clic su Approva in una finestra della console porta il segreto del
    clic (console_click), che il file del token non contiene: e' una
    persona davanti alla console, come per l'invio, e non apre il prompt
    (che su Windows poteva aprirsi dietro le finestre e lasciare il bottone
    fermo). Resta il prompt se l'utente l'ha chiesto anche per la console."""
    from gigamail import consent

    from . import console_click
    rec = policy.store().get(request_id)
    if not rec:
        raise HTTPException(404, "Richiesta inesistente")
    clic = (request is not None and console_click.is_console_click(request.headers)
            and not console_click.send_requires_hello())
    if not clic:
        reason = f"GigaMail: approvare {rec['tool']} ({request_id})?"
        try:
            ok = consent.require_human(reason)
        except consent.ConsentUnavailable as e:
            raise HTTPException(503, str(e)) from e
        if not ok:
            raise HTTPException(403, "Verifica utente non superata o annullata")
    by = f"{_who()} (console click)" if clic else _who()
    if not policy.store().approve(request_id, by=by):
        raise HTTPException(409, "Richiesta non approvabile (già decisa o scaduta)")
    out = {"success": True, "request_id": request_id, "status": "approved",
           "completed_by": _completed_by(request_id)}
    out.update(complete_agent_request(request_id))
    return out


def complete_agent_request(request_id: str) -> dict:
    """An approved request is completed by GigaMail itself, here and now:
    a tool request with the arguments stored with it, a rule's draft
    with the watcher's send path. Before, only the agent bar made the
    agent call the tool again, and a draft waited for the watcher's next
    tick. Returns what was recorded: status, outcome, error."""
    from gigamail import completion
    return completion.complete(request_id)


@router.post("/approvals/{request_id}/reject")
def reject_request(request_id: str):
    if not policy.store().reject(request_id, by=_who()):
        raise HTTPException(409, "Richiesta non rifiutabile (già decisa o scaduta)")
    return {"success": True, "request_id": request_id, "status": "rejected"}


@router.post("/approvals/{request_id}/save")
def save_request(request_id: str, request: Request = None):
    """"Save" from the console: decide later. The request stays in
    "waiting for you" for days instead of minutes. Only a click in the
    console: the agent, holding the token file, cannot keep its own
    requests open."""
    from . import console_click
    if not console_click.is_console_click(request.headers if request else {}):
        raise HTTPException(403, "only from the console")
    if not policy.store().save_for_later(request_id, by=f"{_who()} (console click)"):
        raise HTTPException(409, "Richiesta non salvabile (già decisa o scaduta)")
    rec = policy.store().get(request_id) or {}
    return {"success": True, "request_id": request_id, "status": "pending",
            "saved_at": rec.get("saved_at"), "expires_at": rec.get("expires_at")}


class AddedFile(BaseModel):
    name: str
    data_b64: str


class AmendRequest(BaseModel):
    body: str | None = None
    subject: str | None = None
    attachments: list[AddedFile] | None = None


def _still_waiting(request_id: str) -> bool:
    rec = policy.store().get(request_id)
    return bool(rec and rec["status"] in (policy.PENDING, policy.APPROVED)
                and not rec["expired"])


@router.post("/approvals/{request_id}/amend")
def amend_request(request_id: str, req: AmendRequest, request: Request = None):
    """The approval window's in-place edit: the person rewrites the text of
    a pending request and then approves it, instead of closing it with a
    note and waiting for a new draft. Only the body and the subject can
    change, and only from a click in the console: the recipients stay
    what the agent asked for, and the agent, holding the token file,
    cannot rewrite its own requests. The approval that follows runs the
    amended arguments, from whatever channel it comes.

    The person can also add files to a mail, from anywhere: the agent
    attaches only what is registered for the account, a person picks what
    they want. The bytes come with the click and are kept with the request."""
    from gigamail.core import attachments as attachments_mod

    from . import console_click
    if not console_click.is_console_click(request.headers if request else {}):
        raise HTTPException(403, "only from the console")
    rec = policy.store().get(request_id)
    if not rec:
        raise HTTPException(404, "Richiesta inesistente")
    changes = {k: v for k, v in {"body": req.body, "subject": req.subject}.items()
               if v is not None}
    files = [f.model_dump() for f in req.attachments or []]
    if not changes and not files:
        raise HTTPException(400, "nothing to change")
    missing = [k for k in changes if k not in rec["args"]]
    if missing:
        raise HTTPException(400, f"this request has no {', '.join(missing)} to edit")
    if files and (rec["tool"] not in policy.ApprovalStore.ATTACHABLE_TOOLS
                  or "body" not in rec["args"]):
        raise HTTPException(400, "this request sends no mail: nothing to attach a file to")
    if rec["status"] != policy.PENDING or rec["expired"]:
        raise HTTPException(409, "Non modificabile: già decisa o scaduta")
    try:
        added = attachments_mod.stage(request_id, files, rec["args"].get("attachments"))
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    if not policy.store().amend(request_id, changes, by=f"{_who()} (console click)",
                                add_attachments=added):
        attachments_mod.discard(added)
        raise HTTPException(409, "Non modificabile: nessuna differenza, o già decisa o scaduta")
    try:
        attachments_mod.discard_stale(_still_waiting)
    except Exception:
        pass
    rec = policy.store().get(request_id)
    return {"success": True, "request_id": request_id, "status": rec["status"],
            "preview": rec["preview"]}


class EditRequest(BaseModel):
    note: str = ""


@router.post("/approvals/{request_id}/edit")
def edit_request(request_id: str, req: EditRequest, request: Request = None):
    """"Edit" from the console's popup: a request is frozen to what would
    be executed, so editing means closing THIS one with a note. A draft
    born from a rule is redrafted by the watcher with that note; for the
    agent's own request the note is reported back to the agent. Rejecting
    never needs Hello: it closes a door."""
    from gigamail.watcher.approvals import requeue_with_note

    from . import console_click
    if not console_click.is_console_click(request.headers if request else {}):
        raise HTTPException(403, "only from the console")
    rec = policy.store().get(request_id)
    if not rec:
        raise HTTPException(404, "Richiesta inesistente")
    note = (req.note or "").strip()[:500]
    if not note:
        raise HTTPException(400, "nota vuota")
    who = f"{_who()} modifica: {note[:200]}"
    if rec["status"] == policy.APPROVED:
        ok = policy.store().revoke(request_id, by=who)
    else:
        ok = policy.store().reject(request_id, by=who)
    if not ok:
        raise HTTPException(409, "Non modificabile: già eseguita o scaduta")
    return {"success": True, "request_id": request_id,
            "requeued": requeue_with_note(request_id, note)}


@router.get("/alerts/{key}")
def alert_context(key: str):
    """The client-reply alert behind a desktop "Reply" button."""
    from gigamail.watcher import tg_risposte
    ctx = tg_risposte.contesto(key)
    if not ctx:
        raise HTTPException(404, "avviso non trovato")
    out = dict(ctx)
    try:
        from gigamail.core import mail_router
        m = mail_router.get_message(account_id=ctx.get("account_id"),
                                    message_id=ctx.get("message_id") or "",
                                    folder=ctx.get("folder") or "inbox") or {}
        out["testo"] = str(m.get("body_text") or m.get("bodyPreview") or "")[:4000]
    except Exception:
        out["testo"] = ""
    return out


class AlertReply(BaseModel):
    instruction: str = ""


@router.post("/alerts/{key}/reply")
def alert_reply(key: str, req: AlertReply, request: Request = None):
    """What to answer: the watcher drafts it on its next tick and sends it
    for approval. Nothing is sent here."""
    from gigamail.watcher import tg_risposte

    from . import console_click
    if not console_click.is_console_click(request.headers if request else {}):
        raise HTTPException(403, "only from the console")
    if not tg_risposte.queue_desktop_reply(key, (req.instruction or "").strip()[:2000]):
        raise HTTPException(400, "avviso sconosciuto o istruzione vuota")
    policy.audit("reply_mail", {"alert": key}, "desktop_reply_queued", detail=_who())
    return {"success": True}


@router.get("/audit")
def audit_log(limit: int = 100):
    """Ultime azioni compiute dall'agente (per la vista console)."""
    from gigamail.core.data_paths import app_root
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
