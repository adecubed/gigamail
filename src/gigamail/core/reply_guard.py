# GigaMail — mail for your AI agent
# Copyright (C) 2026 Adecubed
# Licensed under the GNU AGPL v3 or later. See LICENSE.
"""One reply per mail, whichever path drafts it.

A client accepted a time for a video call. Within six minutes three
paths each drafted a reply to that same mail: the confirmation the
watcher drafts at once, the mail with the Zoom link, and a reply asked
from Telegram. policy deduplicates identical payloads only, so three
different texts became three approval requests; two were approved and
both went out.

Every path now asks the same question before drafting: does this mail
already have a reply waiting for approval, or one already sent? The
answer comes from the rules store (the handled rows that every drafting
path records) and from the approval store (requests the MCP server
created without a handled row).
"""
import logging
from typing import Any, Dict, Optional

from gigamail import policy

from . import rules as rules_mod

logger = logging.getLogger("gigamail.reply_guard")

PENDING = "pending"
SENT = "sent"
_TOOL = "reply_mail"


def _request_state(request_id: str) -> Optional[str]:
    """PENDING, SENT or None for a request id, read from the approval
    store: the handled row says "awaiting_approval" until the watcher
    notices the human's decision, so the row alone is not enough."""
    if not request_id:
        return None
    try:
        rec = policy.store().get(request_id)
    except Exception as e:  # pragma: no cover - store unavailable
        logger.debug("approval %s not read: %s", request_id, e)
        return None
    if not rec:
        return None
    if rec["status"] == policy.PENDING and not rec["expired"]:
        return PENDING
    if rec["status"] == policy.APPROVED:
        return PENDING                    # the watcher sends it next tick
    if (rec["status"] == policy.EXECUTED
            and rec.get("execution_outcome") in (None, "ok")):
        return SENT
    return None


def existing_reply(message_id: str,
                   exclude_rule: str = "") -> Optional[Dict[str, Any]]:
    """The reply already drafted for this mail, if there is one.

    Returns {"state": PENDING | SENT, "request_id", "rule_id"}, or None
    when nothing was drafted or every earlier draft was rejected, expired
    or failed. A sent reply wins over a pending one. `exclude_rule` leaves
    out the rows of the caller's own rule (its retries, for instance)."""
    mid = str(message_id or "")
    if not mid:
        return None
    pending: Optional[Dict[str, Any]] = None
    try:
        rows = rules_mod.store().replies_to(mid)
    except Exception as e:  # pragma: no cover - store unavailable
        logger.debug("handled rows for %s not read: %s", mid, e)
        rows = []
    for row in rows:
        if exclude_rule and row.get("rule_id") == exclude_rule:
            continue
        found = {"request_id": row.get("request_id") or "",
                 "rule_id": row.get("rule_id") or ""}
        if row.get("status") == "sent":
            return dict(found, state=SENT)
        if row.get("status") != "awaiting_approval":
            continue
        state = _request_state(found["request_id"])
        if state == SENT:
            return dict(found, state=SENT)
        if state == PENDING and pending is None:
            pending = dict(found, state=PENDING)
    if pending:
        return pending
    # Replies the agent asked for through MCP have no handled row: they
    # live only in the approval store, keyed by the mail they answer.
    try:
        for rec in policy.store().list_pending():
            if rec.get("tool") != _TOOL:
                continue
            if str((rec.get("args") or {}).get("message_id") or "") == mid:
                return {"state": PENDING, "request_id": rec["request_id"],
                        "rule_id": ""}
    except Exception as e:  # pragma: no cover - store unavailable
        logger.debug("pending approvals not read: %s", e)
    return None
