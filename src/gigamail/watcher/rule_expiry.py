"""Tell the user, once, that a reply rule is about to expire or has.

A rule expires by design: it is an approval given in advance, and no
approval lasts for ever. But an expired rule answers nothing and says
nothing: an office found out a month later, from the mail that went
unanswered. Now the user hears it on every notification channel a few
days before (rules.EXPIRY_WARNING_DAYS) and again on the day it expires,
with how to renew it. Each message goes once per expiry date: renewing
moves the date, so the next period warns again.
"""
import time
from typing import Any, Dict

from gigamail import policy
from gigamail.core import rules as rules_mod

# An expired rule is told about only if it expired recently: a rule left
# to expire months ago, before this warning existed, is not news.
_EXPIRED_NEWS_SECONDS = 7 * 86400
_KV_PREFIX = "rule_expiry_told:"


def _label(rule: Dict[str, Any]) -> str:
    values = ", ".join(rule.get("trigger_values") or [])
    if rule.get("trigger_kind") == "folder":
        return ("cartella " if policy.user_lang() == "it" else "folder ") + values
    return values


def _message(rule: Dict[str, Any], expired: bool) -> str:
    rid, label = rule["rule_id"], _label(rule)
    days = int(rule["expiry_days"])
    when = time.strftime("%d/%m %H:%M", time.localtime(rule["expires_at"]))
    if policy.user_lang() == "it":
        head = (f"La regola {rid} ({label}) e' SCADUTA il {when}: non risponde piu' a nessuna mail."
                if expired else
                f"La regola {rid} ({label}) scade il {when}: poi non risponde piu' a nessuna mail.")
        return (f"{head} Per altri {days} giorni: console, Automazioni, Rinnova (Hello), "
                f"oppure gigamail rules renew {rid}")
    head = (f"Rule {rid} ({label}) EXPIRED on {when}: it no longer answers any mail."
            if expired else
            f"Rule {rid} ({label}) expires on {when}: after that it answers no mail.")
    return (f"{head} For another {days} days: console, Automations, Renew (Hello), "
            f"or gigamail rules renew {rid}")


def tick(store=None, now=None) -> int:
    """Send the warnings due; returns how many went out. Never raises."""
    store = store or rules_mod.store()
    now = time.time() if now is None else now
    told = 0
    try:
        rules = store.list_all()
    except Exception:
        return 0
    for rule in rules:
        if rule.get("paused"):
            continue
        expired = rule["expires_at"] <= now
        if expired and now - rule["expires_at"] > _EXPIRED_NEWS_SECONDS:
            continue
        if not expired and rule["expires_at"] - now > rules_mod.EXPIRY_WARNING_DAYS * 86400:
            continue
        key = _KV_PREFIX + rule["rule_id"]
        mark = f"{'expired' if expired else 'expiring'}:{rule['expires_at']:.0f}"
        try:
            if store.kv_get(key) == mark:
                continue
            store.kv_set(key, mark)
        except Exception:
            continue
        policy.audit("watch_rule", {"rule_id": rule["rule_id"]},
                     "rule_expired_told" if expired else "rule_expiring_told")
        policy.notify_approval_requested(
            "-", f"rule_expiry:{rule['rule_id']}",
            {"action": "rule expired" if expired else "rule expiring"},
            message=_message(rule, expired), immediate=True)
        told += 1
    return told
