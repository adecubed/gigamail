"""Notifiche, agente, desktop-setup e onboarding della console."""
import os

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from gigamail import agent_bridge, policy
from gigamail.core import accounts as core_accounts

from . import console_click
from .common import _who

router = APIRouter()


# --- notifiche / agente -----------------------------------------------------

@router.get("/notify/status")
def notify_status():
    from gigamail import consent
    from gigamail.core import desktop_notify, telegram_channel
    tg = telegram_channel.load_config()
    return {
        "agent": agent_bridge.status(),
        "consent_backend": consent.backend_name(),
        "consent_reason": consent.unavailable_reason(),
        "desktop": {
            "enabled": desktop_notify.enabled(),
            "buttons": desktop_notify.actions_supported(),
            # "legacy": HKLM still opens the old ade_mail_agent CLI
            "buttons_off": desktop_notify.buttons_off_reason(),
            "platform": os.name,
        },
        "telegram": {
            "configured": bool(tg),
            "chat_id": tg["chat_id"] if tg else None,
            "approve": bool(tg and tg.get("approve")),
        },
        "command": bool(policy._notify_command()),
        "lang": policy.user_lang(),
        # sends clicked in the console: straight away, or behind the OS prompt
        "console_send_hello": console_click.send_requires_hello(),
    }


class ConsoleSendHelloRequest(BaseModel):
    enabled: bool


@router.post("/console/send-hello")
def set_console_send_hello(req: ConsoleSendHelloRequest, request: Request):
    """The user's choice, from the console's own window only: a request
    without the click secret cannot change it (it would gain nothing, since
    it meets the prompt anyway, but the choice belongs to the person)."""
    if not console_click.is_console_click(request.headers):
        raise HTTPException(403, "Solo dalla console")
    console_click.set_send_requires_hello(req.enabled)
    return {"console_send_hello": console_click.send_requires_hello()}


@router.post("/notify/desktop-setup")
def notify_desktop_setup():
    """Rende cliccabili i bottoni della toast (HKLM, prompt UAC)."""
    from gigamail.core import desktop_notify
    if os.name != "nt":
        return {"buttons": False, "note": "solo Windows"}
    desktop_notify._win_register_aumid()
    ok = desktop_notify.register_protocol_machine()
    policy.audit("notify", {"buttons": ok}, "desktop_setup", detail=_who())
    return {"buttons": ok}


# ── ONBOARDING ───────────────────────────────────────────────────────
# La console apre la guida iniziale al primo avvio (nessun account, flag
# non ancora scritto) e la puo' riaprire quando vuole; il flag vive nel
# KV di %APPDATA%/ADE, non nel localStorage di Electron, cosi' un
# reinstall della console non la ripropone a chi ha gia' tutto.

@router.get("/onboarding")
def onboarding_status():
    from gigamail.core import rules as rules_mod
    done = rules_mod.store().kv_get("onboarding_done", "") == "1"
    return {"done": done, "accounts": len(core_accounts.get_accounts()),
            "platform": os.name}


@router.post("/onboarding/done")
def onboarding_done():
    from gigamail.core import rules as rules_mod
    rules_mod.store().kv_set("onboarding_done", "1")
    return {"done": True}
