"""Notifiche, agente, desktop-setup e onboarding della console."""
import os

from fastapi import APIRouter

from ade_mail_agent import agent_bridge, policy
from ade_mail_agent.core import accounts as core_accounts

from .common import _who

router = APIRouter()


# --- notifiche / agente -----------------------------------------------------

@router.get("/notify/status")
def notify_status():
    from ade_mail_agent import consent
    from ade_mail_agent.core import desktop_notify, telegram_channel
    tg = telegram_channel.load_config()
    return {
        "agent": agent_bridge.status(),
        "consent_backend": consent.backend_name(),
        "desktop": {
            "enabled": desktop_notify.enabled(),
            "buttons": desktop_notify.actions_supported(),
            "platform": os.name,
        },
        "telegram": {
            "configured": bool(tg),
            "chat_id": tg["chat_id"] if tg else None,
            "approve": bool(tg and tg.get("approve")),
        },
        "command": bool(policy._notify_command()),
        "lang": policy.user_lang(),
    }


@router.post("/notify/desktop-setup")
def notify_desktop_setup():
    """Rende cliccabili i bottoni della toast (HKLM, prompt UAC)."""
    from ade_mail_agent.core import desktop_notify
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
    from ade_mail_agent.core import rules as rules_mod
    done = rules_mod.store().kv_get("onboarding_done", "") == "1"
    return {"done": done, "accounts": len(core_accounts.get_accounts()),
            "platform": os.name}


@router.post("/onboarding/done")
def onboarding_done():
    from ade_mail_agent.core import rules as rules_mod
    rules_mod.store().kv_set("onboarding_done", "1")
    return {"done": True}
