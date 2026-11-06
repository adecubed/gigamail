"""Selectors with combinators, for the rules that may hide text in a mail.

html_text evaluates simple selectors (tag, #id, .class) exactly. A rule
whose selector it could not read and that hides something used to mark
the whole mail as not checked, and the agent got nothing: one HTML mail
in five, mostly templates (Beefree's `.image_block img+div`, Gmail's
`u + .body .x`, Outlook's `[data-ogsc] .x`) whose rules hide nothing a
reader of this document sees.

This module reads those selectors and matches them, leaning towards
matching too much, because a match only ever hides text from the agent
(html_text never lets a rule found here show text it would hide):

- the rightmost compound is matched exactly on tag, id, classes and
  attributes; a pseudo-class it does not evaluate is dropped, which only
  widens the match;
- a compound to its left may name what a mail client injects around the
  message (`u`, `body`, `[data-ogsc]`, `.ExternalClass`, `#MessageViewBody`
  ...). The document cannot show whether it is there, so it counts as
  present;
- Gmail puts a <div> after every <img>: `+` and `~` see it too.

A rule that cannot hide document text (::before, :hover, :empty on the
element itself) is dropped. A selector it cannot read at all (`.&`)
stays a reason to withhold the mail.
"""
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

# Pseudo-elements and states that leave the element's own text as it is.
_PSEUDO_ELEMENTS_IGNORED = re.compile(
    r"^(before|after|placeholder|selection|marker|backdrop|file-selector-button"
    r"|-webkit-.*|-moz-.*|-ms-.*)$", re.IGNORECASE)
# Pseudo-elements that do style the element's own text.
_PSEUDO_ELEMENTS_TEXT = {"first-line", "first-letter"}
# The text shows until the reader interacts: the rule does not hide it.
_STATES_IGNORED = {"hover", "focus", "active", "focus-within", "focus-visible", "visited"}
# What mail clients wrap the message in, or rename it to.
_INJECTED_TAGS = {"u", "body", "html"}
_INJECTED_NAME = re.compile(
    r"^(externalclass|readmsgbody|messageviewbody|messagewebviewdiv|x_|ogs|gmail"
    r"|apple|yiv|ii\b|a3s|ms-outlook|outlook)", re.IGNORECASE)


@dataclass
class El:
    """An element as the selector sees it."""
    tag: str
    id: str = ""
    classes: frozenset = frozenset()
    attrs: dict = field(default_factory=dict)
    parent: Optional["El"] = None
    prev: Tuple["El", ...] = ()     # earlier siblings, nearest last


@dataclass
class Compound:
    tag: str = ""
    ids: Tuple[str, ...] = ()
    classes: Tuple[str, ...] = ()
    attrs: Tuple[Tuple[str, str, str], ...] = ()   # (name, op, value)
    checked: bool = False      # :checked, read from the checked attribute
    link: bool = False         # :link / :any-link, read from href
    injected: bool = False     # may name what a client adds: counts as present
    unreadable: bool = False
    widened: bool = False      # a pseudo-class was dropped: matches more

    def matches(self, el: El) -> bool:
        if self.tag and self.tag != "*" and self.tag != el.tag:
            return False
        if self.ids and any(i != el.id for i in self.ids):
            return False
        if self.classes and not set(self.classes) <= el.classes:
            return False
        if self.checked and "checked" not in el.attrs:
            return False
        if self.link and not (el.tag in ("a", "area") and "href" in el.attrs):
            return False
        for name, op, value in self.attrs:
            if name not in el.attrs:
                return False
            got = el.attrs[name]
            if op == "=" and got != value:
                return False
            if op == "~=" and value not in got.split():
                return False
            if op == "^=" and not got.startswith(value):
                return False
            if op == "$=" and not got.endswith(value):
                return False
            if op == "*=" and value not in got:
                return False
            if op == "|=" and not (got == value or got.startswith(value + "-")):
                return False
        return True


@dataclass
class Selector:
    compounds: List[Compound]
    combinators: List[str]      # between compounds: " ", ">", "+", "~"

    def matches(self, el: El) -> bool:
        return _match(self, len(self.compounds) - 1, el, 0, {})

    @property
    def exact(self) -> bool:
        """Matched as a browser would: no compound taken for present or
        widened. Only such a rule may lend a colour (a wider match of a
        colour can hide text a reader sees as well as text a reader
        does not)."""
        return not any(c.injected or c.widened or c.unreadable for c in self.compounds)


_GMAIL_DIV = "div"


def _siblings_before(el: El):
    """Earlier siblings, nearest first, with the <div> Gmail adds after
    every <img>."""
    for sib in reversed(el.prev):
        if sib.tag == "img":
            yield El(_GMAIL_DIV, parent=el.parent, prev=el.prev)
        yield sib


def _match(sel: Selector, i: int, el: El, depth: int, memo: dict) -> bool:
    """Whether compounds[:i+1] match with compounds[i] on `el`. `memo`
    keeps what is known per (compound, element): without it `div div div
    p` on a deep tree takes time exponential in the selector's length."""
    key = (i, id(el))
    if key not in memo:
        # the element is kept with the answer: a virtual Gmail <div> lives
        # only during the match, and a freed object's id can be reused
        memo[key] = (_match_once(sel, i, el, depth, memo), el)
    return memo[key][0]


def _match_once(sel: Selector, i: int, el: El, depth: int, memo: dict) -> bool:
    if depth > 200:
        return True     # pathological nesting: match, the safe side
    comp = sel.compounds[i]
    if i < len(sel.compounds) - 1 and comp.injected:
        return True
    if not comp.matches(el):
        return False
    if i == 0:
        return True
    left, comb = i - 1, sel.combinators[i - 1]
    if sel.compounds[left].injected:
        return True
    if comb == ">":
        return el.parent is not None and _match(sel, left, el.parent, depth + 1, memo)
    if comb == " ":
        a = el.parent
        while a is not None:
            if _match(sel, left, a, depth + 1, memo):
                return True
            a = a.parent
        return False
    if comb == "+":
        first = next(_siblings_before(el), None)
        if first is None:
            return False
        # the Gmail <div> sits right after an <img>: both are "just before"
        if first.tag == _GMAIL_DIV and el.prev and el.prev[-1].tag == "img":
            return (_match(sel, left, first, depth + 1, memo)
                    or _match(sel, left, el.prev[-1], depth + 1, memo))
        return _match(sel, left, first, depth + 1, memo)
    if comb == "~":
        return any(_match(sel, left, s, depth + 1, memo) for s in _siblings_before(el))
    return True


# ── parsing ────────────────────────────────────────────────────────

class _Unreadable(Exception):
    pass


class Ignore(Exception):
    """The rule cannot hide document text: drop it."""


def _paren(s: str, i: int) -> int:
    """Index after the parenthesis that closes the one at s[i]."""
    depth = 0
    for j in range(i, len(s)):
        if s[j] == "(":
            depth += 1
        elif s[j] == ")":
            depth -= 1
            if depth == 0:
                return j + 1
    raise _Unreadable()


_NAME = re.compile(r"-?[_a-zA-Z][\w-]*|\*")
_ATTR = re.compile(r"""\[\s*([\w-]+)\s*(?:([~|^$*]?=)\s*("[^"]*"|'[^']*'|[^\]\s]+)\s*(?:[is])?\s*)?\]""",
                   re.IGNORECASE)


def _compound(s: str, rightmost: bool) -> Compound:
    c = Compound()
    i, n = 0, len(s)
    m = _NAME.match(s)
    if m:
        c.tag = m.group(0).lower()
        i = m.end()
    ids, classes, attrs = [], [], []
    while i < n:
        ch = s[i]
        if ch in "#.":
            m = _NAME.match(s, i + 1)
            if not m or m.group(0) == "*":
                raise _Unreadable()
            (ids if ch == "#" else classes).append(m.group(0))
            i = m.end()
        elif ch == "[":
            m = _ATTR.match(s, i)
            if not m:
                raise _Unreadable()
            value = (m.group(3) or "").strip("\"'")
            attrs.append((m.group(1).lower(), m.group(2) or "", value))
            i = m.end()
        elif ch == ":":
            element = s.startswith("::", i)
            i += 2 if element else 1
            m = _NAME.match(s, i)
            if not m:
                raise _Unreadable()
            name = m.group(0).lower()
            i = m.end()
            if i < n and s[i] == "(":
                i = _paren(s, i)
            legacy_element = name in ("before", "after", "first-line", "first-letter")
            if element or legacy_element:
                if not rightmost:
                    raise Ignore()      # invalid there: browsers drop the rule
                if name in _PSEUDO_ELEMENTS_TEXT:
                    continue
                if _PSEUDO_ELEMENTS_IGNORED.match(name) or legacy_element:
                    raise Ignore()
                raise _Unreadable()
            if name in _STATES_IGNORED:
                raise Ignore()
            if name == "empty" and rightmost:
                raise Ignore()          # an empty element has no text to hide
            if name == "checked":
                c.checked = True
            elif name in ("link", "any-link"):
                c.link = True
            else:
                # any other pseudo-class (:not, :nth-child, :root, ...) is
                # dropped: the match only gets wider
                c.widened = True
        else:
            raise _Unreadable()
    c.ids, c.classes, c.attrs = tuple(ids), tuple(classes), tuple(attrs)
    c.injected = bool(attrs) or c.tag in _INJECTED_TAGS or any(
        _INJECTED_NAME.match(x) for x in ids + classes)
    return c


def _split(sel: str) -> Tuple[List[str], List[str]]:
    """Compounds and the combinators between them, brackets and
    parentheses respected."""
    parts, combs, cur, i, n = [], [], "", 0, len(sel)
    pending = None
    while i < n:
        ch = sel[i]
        if ch in "([":
            j = _paren(sel, i) if ch == "(" else sel.find("]", i) + 1
            if j <= 0:
                raise _Unreadable()
            cur += sel[i:j]
            i = j
            continue
        if ch in " \t\n\r\f>+~":
            if cur:
                parts.append(cur)
                cur = ""
                pending = " "
            if ch != " " and ch not in "\t\n\r\f":
                if pending is None and not parts:
                    raise _Unreadable()
                pending = ch
            i += 1
            continue
        if pending is not None:
            combs.append(pending)
            pending = None
        cur += ch
        i += 1
    if cur:
        parts.append(cur)
    if not parts or len(combs) != len(parts) - 1 or (pending and pending != " "):
        raise _Unreadable()
    return parts, combs


def parse(sel: str) -> Optional[Selector]:
    """A Selector; None when the rule cannot hide document text. Raises
    ValueError when the selector cannot be read."""
    try:
        parts, combs = _split(sel.strip())
        compounds = []
        for k, part in enumerate(parts):
            rightmost = k == len(parts) - 1
            try:
                compounds.append(_compound(part, rightmost))
            except _Unreadable:
                if rightmost:
                    raise
                compounds.append(Compound(injected=True, unreadable=True))
        return Selector(compounds, combs)
    except Ignore:
        return None
    except _Unreadable as e:
        raise ValueError(f"unreadable selector: {sel[:60]}") from e
