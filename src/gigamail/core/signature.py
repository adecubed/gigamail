# GigaMail — mail for your AI agent
# Copyright (C) 2026 Adecubed
# Licensed under the GNU AGPL v3 or later. See LICENSE.
"""Per-account signature appended to every outgoing mail.

The signature is added when an approval request is BUILT, never when it
is executed: the preview the human approves already ends with it, and
the approved payload is sent unchanged. It is plain text set by the user
(console or CLI); no MCP tool can change it, so an agent cannot slip
text into every mail the user approves.

An empty signature (the default) adds nothing of the user's own.

Below it goes one line saying the mail was sent with GigaMail, as
mobile mail apps do ("Sent from Outlook for Android"): "Sent via
gigamail.ai", in English for every user, with the site's domain as plain
text so whoever reads it can find GigaMail (most mail apps turn the
domain into a link on their own). It is on by default and can be
switched off per account.
"""
from gigamail.core import accounts

# The video-call confirmation read an Italian key that nothing ever wrote;
# it is still honoured as a fallback so a value set by hand is not lost.
_LEGACY_KEY = "firma_account_{}"
_KEY = "signature_account_{}"
_SENT_VIA_KEY = "sent_via_account_{}"
SENT_VIA = "Sent via gigamail.ai"
# Every wording the line ever had: a body that already ends with one of
# them (a redraft, a draft signed by an earlier version) is not tagged
# twice.
_EVERY_LINE = (
    SENT_VIA,
    "Sent via GigaMail Desktop",
    "Inviato da GigaMail Desktop",
)
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


def sent_via_enabled(account_id) -> bool:
    """Whether mail from this account ends with the "Sent via
    gigamail.ai" line. On unless the user switched it off."""
    if account_id is None:
        return True
    try:
        value = accounts.get_setting(_SENT_VIA_KEY.format(int(account_id)), "1")
    except Exception:
        return True
    return str(value).strip() != "0"


def set_sent_via(account_id: int, enabled: bool) -> bool:
    accounts.set_setting(_SENT_VIA_KEY.format(int(account_id)), "1" if enabled else "0")
    return bool(enabled)


def sent_via_line() -> str:
    """The line, the same for every user."""
    return SENT_VIA


def apply(account_id, body: str) -> str:
    """`body` with the account's signature at the bottom, then the
    "Sent via gigamail.ai" line when it is on.

    Idempotent: a body that already ends with the signature or with the
    line (a redraft of a signed draft, a template that writes it itself)
    is not signed again, so nothing ever appears twice."""
    body = body or ""
    text = body.rstrip()
    if any(text.endswith(line) for line in _EVERY_LINE):
        return body
    sig = get(account_id)
    added = False
    if sig and not text.endswith(sig):
        text += "\n\n" + sig
        added = True
    if sent_via_enabled(account_id):
        text += "\n\n" + sent_via_line()
        added = True
    return text + "\n" if added else body
