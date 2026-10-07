# GigaMail — mail for your AI agent
# Copyright (C) 2026 Adecubed
# Licensed under the GNU AGPL v3 or later. See LICENSE.
"""Per-account signature appended to every outgoing mail.

The signature is added when an approval request is BUILT, never when it
is executed: the preview the human approves already ends with it, and
the approved payload is sent unchanged. It is plain text set by the user
(console or CLI); no MCP tool can change it, so an agent cannot slip
text into every mail the user approves.

An empty signature (the default) changes nothing.
"""
from gigamail.core import accounts

# The video-call confirmation read an Italian key that nothing ever wrote;
# it is still honoured as a fallback so a value set by hand is not lost.
_LEGACY_KEY = "firma_account_{}"
_KEY = "signature_account_{}"
MAX_CHARS = 1000


def get(account_id) -> str:
    """The account's signature, "" when none is set or it cannot be read."""
    if account_id is None:
        return ""
    try:
        aid = int(account_id)
        value = accounts.get_setting(_KEY.format(aid), None)
        if value is None:
            value = accounts.get_setting(_LEGACY_KEY.format(aid), "")
    except Exception:
        return ""
    return str(value or "").strip()


def save(account_id: int, text: str) -> str:
    """Store the signature (trimmed, at most MAX_CHARS); "" removes it."""
    value = str(text or "").replace("\r\n", "\n").strip()
    if len(value) > MAX_CHARS:
        raise ValueError(f"Signature longer than {MAX_CHARS} characters")
    accounts.set_setting(_KEY.format(int(account_id)), value)
    return value


def apply(account_id, body: str) -> str:
    """`body` with the account's signature at the bottom.

    Idempotent: a body that already ends with the signature (a redraft
    of a signed draft, a template that writes it itself) is returned as
    it is, so the signature never appears twice."""
    body = body or ""
    sig = get(account_id)
    if not sig:
        return body
    if body.rstrip().endswith(sig):
        return body
    return body.rstrip() + "\n\n" + sig + "\n"
