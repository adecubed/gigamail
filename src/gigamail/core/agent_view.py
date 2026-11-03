# GigaMail — mail for your AI agent
# Copyright (C) 2026 Adecubed
# Licensed under the GNU AGPL v3 or later. See LICENSE.
"""What an MCP answer may carry to the agent: every string, not only the body.

The body is read with care (core/html_text, core/injection_guard,
core/link_guard), but a mail reaches the agent through other fields too: the
sender's display name, the recipients' names, attachment names, the subject
inside an action preview (delete_message, move_message, reply_mail show it
before anyone approves). A check that covers the body and leaves those open
is a check with a side door. So every MCP answer that carries mail data goes
through scrub() last: every string in it, at any depth, loses its invisible
characters and its URLs, and a string that gives an assistant orders is
replaced whole.

The person's copy is never touched: approval previews are stored as they
were built and the console, Telegram and the toast show them in full. Only
the copy returned to the agent is scrubbed.
"""
from typing import Any, Iterable

from gigamail.core import html_text, injection_guard, link_guard

WITHHELD = "(withheld by GigaMail: instructions to an assistant)"

# GigaMail's own notes to the agent: written here, not by a sender. Some of
# them warn in the imperative ("do not run it"), which the check would read
# as an order.
OWN_NOTES = frozenset({"withheld", "hidden_text", "warning", "instructions", "truncated",
                       # built by core/link_guard from text that was already
                       # checked: number, host, link text cut to its host
                       "links"})


def clean(text: str) -> str:
    text = html_text.strip_invisible(text)[0]
    if injection_guard.check("", text).blocked:
        return WITHHELD
    return link_guard.redact_plain(text)


def scrub(value: Any, keep: Iterable[str] = OWN_NOTES) -> Any:
    """A copy of `value` with every string cleaned; values under the keys in
    `keep` pass as they are (GigaMail's own notes)."""
    keep = frozenset(keep)
    if isinstance(value, str):
        return clean(value)
    if isinstance(value, dict):
        return {k: (v if k in keep else scrub(v, keep)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [scrub(v, keep) for v in value]
    return value


def mailto_address(url: str) -> str:
    """The address of a mailto: link, nothing else: a mailto can carry a
    subject and a body in its query, and those are text from the sender."""
    from urllib.parse import unquote
    addr = unquote(url[len("mailto:"):] if url.lower().startswith("mailto:") else url)
    addr = addr.split("?", 1)[0].split(",", 1)[0].strip()
    return addr if "@" in addr and " " not in addr else ""
