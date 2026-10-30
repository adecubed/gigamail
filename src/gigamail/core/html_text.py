"""Plain text from a mail's HTML: only what a person reading the mail sees.

Stripping tags alone is not enough for mail written in Outlook: its HTML
carries a <style> block inside conditional comments
(<!--[if !mso]><style>v\\:* {behavior:url(#default#VML);} ...</style><![endif]-->),
and once the tags are gone the CSS rules stay in the text. The list
preview and the Telegram alert then opened with "v\\:* {behavior:..." and
with raw entities such as &nbsp;.

Stripping tags is not safe either. A mail can carry text the reader never
sees: a paragraph with display:none or font-size:0, white text on a white
background, a block pushed off screen, characters of zero width, Unicode
"tag" characters that spell out words no font draws. A person approves
what the console shows; an agent fed the stripped tags reads all of it,
and an instruction hidden there is addressed to the agent alone. This
module returns the visible text and, apart, what was hidden.

It reads in two passes: every <style> block first, wherever it sits in
the document, then the body. Rules apply by compound selector (tag, #id
and every .class must match) with !important and the inline style
cascading over them. What it cannot evaluate it does not guess at: a
hiding rule with a selector it does not support, an external style sheet
or a parser error marks the result as not checked, and a caller handing
text to an agent withholds it (`checked` is False). The one external
sheet it accepts is Google Fonts: it only declares fonts, and Google
serves it, not the sender. Over-hiding is the
safe side: text wrongly taken for hidden is only left out of what the
agent reads, and the person still sees the mail in the console.
"""
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlsplit

_SPACES = re.compile(r"[ \t\r\f\v\u00a0]+")
_BLANK_LINES = re.compile(r"\n\s*\n+")

# Characters that take no room on screen: zero-width spaces and joiners,
# bidirectional controls, the soft hyphen, the BOM and the Unicode "tag"
# block (U+E0000-U+E007F), which encodes ASCII that models read and fonts
# do not draw.
_INVISIBLE = re.compile(
    "[\u00ad\u180e\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u2069\ufeff"
    "\U000e0000-\U000e007f]"
)

# Elements whose content is never shown as text.
_SKIPPED = {"head", "style", "script", "title", "xml", "template", "noscript", "svg"}
# Elements that close themselves: never on the open-element stack.
_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
         "meta", "param", "source", "track", "wbr"}
# Elements whose end starts a new line, as before.
_BREAK_AFTER = {"p", "div", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6"}

_NAMED_COLOURS = {
    "white": (255, 255, 255), "black": (0, 0, 0), "red": (255, 0, 0),
    "green": (0, 128, 0), "blue": (0, 0, 255), "gray": (128, 128, 128),
    "grey": (128, 128, 128), "silver": (192, 192, 192), "yellow": (255, 255, 0),
    "whitesmoke": (245, 245, 245), "snow": (255, 250, 250),
    "ghostwhite": (248, 248, 255), "ivory": (255, 255, 240),
}
_DEFAULT_BG = (255, 255, 255)
_DEFAULT_FG = (0, 0, 0)
# Text this close to its background (Euclidean RGB distance) is not read.
_SAME_COLOUR = 24
_MAX_LINKS = 50
_IMPORTANT = re.compile(r"!\s*important\s*$", re.IGNORECASE)
_SIMPLE_SELECTOR = re.compile(r"^(\*|[a-z][\w-]*)?((?:[.#][\w-]+)*)$", re.IGNORECASE)
# `@import url("x") media;` and `@import "x";`: group 1 is the address.
_IMPORT = re.compile(r"""@import\s+(?:url\(\s*)?["']?([^"')\s;]*)["']?\s*\)?[^;{}]*;?""",
                     re.IGNORECASE)
_FONT_SHEET_HOST = "fonts.googleapis.com"


def _font_sheet(url: str) -> bool:
    """A Google Fonts style sheet: its host exactly, no user, no port."""
    try:
        u = urlsplit((url or "").strip())
        return (u.scheme.lower() in ("https", "http", "")
                and (u.hostname or "") == _FONT_SHEET_HOST
                and u.port is None and "@" not in u.netloc)
    except ValueError:
        return False


@dataclass
class VisibleText:
    text: str
    hidden_text: str
    invisible_chars: int
    hidden_markup_chars: int = 0
    # False when the markup could not be fully evaluated: a parser error,
    # a hiding rule with a selector this reader does not support, an
    # external style sheet. Text for an agent must then be withheld.
    checked: bool = True
    reason: str = ""
    # Links a person sees: (text, url), http(s) and mailto only.
    links: Tuple[Tuple[str, str], ...] = ()

    @property
    def hidden_chars(self) -> int:
        """Characters a reader does not see: text hidden by the markup
        (spaces excluded) plus invisible characters. The ASCII that tag
        characters spell is in hidden_text but counted once, as invisible."""
        return self.hidden_markup_chars + self.invisible_chars


def smuggled_ascii(text: str) -> str:
    """The ASCII spelled by Unicode tag characters (U+E0020-U+E007E): a
    model reads it, a screen shows nothing. Kept for the injection check."""
    return "".join(chr(ord(c) - 0xE0000) for c in str(text or "")
                   if 0xE0020 <= ord(c) <= 0xE007E)


def strip_invisible(text: str) -> Tuple[str, int]:
    """`text` without zero-width, bidi-control and tag characters, and how
    many there were."""
    text = str(text or "")
    cleaned, count = _INVISIBLE.subn("", text)
    return cleaned, count


# ── CSS values ─────────────────────────────────────────────────────

def _colour(value: str) -> Optional[Tuple[int, ...]]:
    """An RGB tuple, () for transparent, None when unreadable. Never raises:
    a malformed colour in a hostile mail must not stop the reading."""
    v = (value or "").strip().lower()
    if not v:
        return None
    if v == "transparent":
        return ()
    if v in _NAMED_COLOURS:
        return _NAMED_COLOURS[v]
    m = re.fullmatch(r"#([0-9a-f]{3}|[0-9a-f]{6})", v)
    if m:
        h = m.group(1)
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    m = re.fullmatch(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([^)]*?)\s*)?\)", v)
    if m:
        alpha = m.group(4)
        if alpha is not None:
            try:
                if float(alpha.rstrip("%")) / (100 if alpha.endswith("%") else 1) < 0.1:
                    return ()
            except ValueError:
                return None
        return tuple(min(255, int(m.group(i))) for i in (1, 2, 3))
    return None


def _first_colour(value: str) -> Optional[Tuple[int, ...]]:
    """The colour in a `background` shorthand ("#fff url(x) no-repeat")."""
    for token in re.findall(r"rgba?\([^)]*\)|#[0-9a-fA-F]{3,6}\b|[a-zA-Z]+", value or ""):
        c = _colour(token)
        if c is not None:
            return c
    return None


def _close(a: Tuple[int, ...], b: Tuple[int, ...]) -> bool:
    if a == () or b == ():
        return False
    return sum((x - y) ** 2 for x, y in zip(a, b, strict=False)) ** 0.5 <= _SAME_COLOUR


def _declarations(value: str) -> Dict[str, Tuple[str, bool]]:
    """{property: (value, important)} from a style attribute or rule body."""
    out = {}
    for decl in (value or "").split(";"):
        if ":" not in decl:
            continue
        k, v = decl.split(":", 1)
        prop = k.strip().lower()
        important = bool(_IMPORTANT.search(v))
        if not important and out.get(prop, ("", False))[1]:
            continue    # a later normal declaration does not beat !important
        out[prop] = (_IMPORTANT.sub("", v).strip().lower(), important)
    return out


def _length(value: str) -> Optional[float]:
    """A CSS length in px-ish units: 0 for any zero, None if unreadable."""
    m = re.match(r"^(-?[\d.]+)\s*(px|pt|em|rem|%|cm|mm|in|vh|vw)?$", (value or "").strip())
    if not m:
        return None
    try:
        n = float(m.group(1))
    except ValueError:
        return None
    unit = m.group(2) or "px"
    return n * {"em": 16, "rem": 16, "pt": 1.33, "cm": 37.8, "mm": 3.78, "in": 96}.get(unit, 1)


def _hides(props: Dict[str, str]) -> bool:
    """True when these declarations make an element's text unreadable."""
    if props.get("display") == "none":
        return True
    if props.get("visibility") in ("hidden", "collapse"):
        return True
    try:
        if float(props.get("opacity", "1")) < 0.1:
            return True
    except ValueError:
        pass
    size = _length(props.get("font-size", ""))
    if size is not None and size <= 1:
        return True
    # A box shrunk to nothing hides its text only when overflow is clipped
    # (the newsletter "preheader" trick: max-height:0; overflow:hidden).
    if props.get("overflow") == "hidden":
        for dim in ("height", "max-height", "width", "max-width"):
            n = _length(props.get(dim, ""))
            if n is not None and n <= 1:
                return True
    for offset in ("text-indent", "left", "top", "margin-left", "margin-top"):
        n = _length(props.get(offset, ""))
        if n is not None and n <= -500:
            return True
    if re.match(r"rect\(\s*0", props.get("clip", "")):
        return True
    if re.search(r"scale\(\s*0(\.0+)?\s*[,)]", props.get("transform", "")):
        return True
    if _colour(props.get("color", "")) == ():
        return True
    return False


# ── style sheets ───────────────────────────────────────────────────

@dataclass
class _Rule:
    tag: str
    ids: frozenset
    classes: frozenset
    decls: Dict[str, Tuple[str, bool]]

    def matches(self, tag: str, el_id: str, classes: set) -> bool:
        return ((not self.tag or self.tag == "*" or self.tag == tag)
                and self.ids <= ({el_id} if el_id else set())
                and self.classes <= classes)


def _without_at_blocks(css: str) -> str:
    """The sheet without @media / @supports / ... blocks (nested braces
    included): their rules apply to some screens only."""
    out, i = [], 0
    while i < len(css):
        if css.startswith("@", i):
            j, k = css.find("{", i), css.find(";", i)
            if j == -1 or (k != -1 and k < j):
                i = (k + 1) if k != -1 else len(css)
                continue
            depth, i = 1, j + 1
            while i < len(css) and depth:
                depth += {"{": 1, "}": -1}.get(css[i], 0)
                i += 1
            continue
        out.append(css[i])
        i += 1
    return "".join(out)


def _parse_sheet(css: str) -> Tuple[List[_Rule], str]:
    """(rules with simple selectors, why it cannot be checked or '')."""
    css = re.sub(r"/\*.*?\*/", "", css or "", flags=re.S)
    if any(not _font_sheet(m.group(1)) for m in _IMPORT.finditer(css)):
        return [], "external style sheet (@import)"
    css = _IMPORT.sub("", css)
    if re.search(r"@import\b", css, re.IGNORECASE):
        return [], "external style sheet (@import)"
    rules, unsupported = [], ""
    for selectors, body in re.findall(r"([^{}]+)\{([^{}]*)\}", _without_at_blocks(css)):
        decls = _declarations(body)
        if not decls:
            continue
        for sel in selectors.split(","):
            sel = sel.strip()
            if not sel:
                continue
            m = _SIMPLE_SELECTOR.match(sel)
            if not m:
                # Descendant, attribute or pseudo selectors are not
                # evaluated. Harmless unless the rule hides something.
                if _hides({k: v for k, (v, _imp) in decls.items()}):
                    unsupported = f"hiding rule with an unsupported selector: {sel[:60]}"
                continue
            rest = m.group(2) or ""
            rules.append(_Rule(
                tag=(m.group(1) or "").lower(),
                ids=frozenset(re.findall(r"#([\w-]+)", rest)),
                classes=frozenset(re.findall(r"\.([\w-]+)", rest)),
                decls=decls))
    return rules, unsupported


def _cascade(rules: List[_Rule], tag: str, el_id: str, classes: set,
             inline: Dict[str, Tuple[str, bool]]) -> Dict[str, str]:
    """The declarations that win on an element: matching rules in document
    order, !important over normal, the inline style over normal rules and
    an !important inline style over everything. Specificity between rules
    is not weighed: the later one wins."""
    won: Dict[str, Tuple[str, bool, bool]] = {}   # prop -> (value, important, inline)

    def put(prop, value, important, is_inline):
        old = won.get(prop)
        if old is None or important or not old[1]:
            if old is not None and old[1] and not important:
                return
            won[prop] = (value, important, is_inline)

    for r in rules:
        if r.matches(tag, el_id, classes):
            for prop, (value, important) in r.decls.items():
                put(prop, value, important, False)
    for prop, (value, important) in inline.items():
        old = won.get(prop)
        if old is not None and old[1] and not important:
            continue
        won[prop] = (value, important, True)
    return {k: v[0] for k, v in won.items()}


# ── the document ───────────────────────────────────────────────────

class _Sheets(HTMLParser):
    """First pass: every <style> block and whether an external sheet is
    linked, wherever they sit in the document."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.css: List[str] = []
        self.external = False
        self._in_style = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag == "style":
            self._in_style += 1
        elif tag == "link":
            a = {k.lower(): (v or "").lower() for k, v in attrs}
            if "stylesheet" in a.get("rel", "") and not _font_sheet(a.get("href", "")):
                self.external = True

    def handle_endtag(self, tag):
        if tag.lower() == "style" and self._in_style:
            self._in_style -= 1

    def handle_data(self, data):
        if self._in_style:
            self.css.append(data)


class _Extractor(HTMLParser):
    def __init__(self, rules: List[_Rule]):
        super().__init__(convert_charrefs=True)
        self.rules = rules
        # each open element: (tag, hidden, foreground, background)
        self.stack: List[Tuple[str, bool, Tuple[int, ...], Tuple[int, ...]]] = []
        self.skip_depth = 0
        self.visible: List[str] = []
        self.hidden: List[str] = []
        # the open <a> whose text is being collected: [href, parts, has_image]
        self.anchor: Optional[list] = None
        self.links: List[Tuple[str, str]] = []

    def _state(self):
        if self.stack:
            _t, hidden, fg, bg = self.stack[-1]
            return hidden, fg, bg
        return False, _DEFAULT_FG, _DEFAULT_BG

    def _out(self, piece: str, hidden: bool) -> None:
        (self.hidden if hidden else self.visible).append(piece)

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in _SKIPPED:
            self.skip_depth += 1
            return
        if self.skip_depth:
            return
        hidden, fg, bg = self._state()
        a = {k.lower(): (v or "") for k, v in attrs}
        props = _cascade(self.rules, tag, a.get("id", ""), set(a.get("class", "").split()),
                         _declarations(a.get("style", "")))
        if ("hidden" in a or _hides(props)
                or (tag == "input" and a.get("type", "").lower() == "hidden")):
            hidden = True
        new_bg = (_first_colour(props.get("background-color", ""))
                  or _first_colour(props.get("background", "")) or _colour(a.get("bgcolor", "")))
        if new_bg:
            bg = new_bg
        new_fg = _colour(props.get("color", "")) or (_colour(a.get("color", "")) if tag == "font" else None)
        if new_fg:
            fg = new_fg
        # The colour test runs on the text itself (handle_data): a dark
        # cell is not hidden, only text the colour of its background is.
        if tag == "a" and not hidden:
            href = strip_invisible(a.get("href", ""))[0].strip()
            if re.match(r"^(https?:|mailto:)", href, re.IGNORECASE):
                self.anchor = [href, [], False]
        elif tag == "img" and not hidden and self.anchor is not None:
            self.anchor[2] = True
        if tag == "br":
            self._out("\n", hidden)
        elif tag not in _VOID:
            self.stack.append((tag, hidden, fg, bg))
        self._out(" ", hidden)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        tag = tag.lower()
        if tag in _SKIPPED:
            if self.skip_depth:
                self.skip_depth -= 1
        elif tag not in _VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in _SKIPPED:
            if self.skip_depth:
                self.skip_depth -= 1
            return
        if self.skip_depth:
            return
        if tag == "a" and self.anchor is not None:
            href, parts, has_image = self.anchor
            text = re.sub(r"\s+", " ", strip_invisible("".join(parts))[0]).strip()
            if text or has_image:
                self.links.append((text, href))
            self.anchor = None
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                hidden = self.stack[i][1]
                del self.stack[i:]
                self._out("\n" if tag in _BREAK_AFTER else " ", hidden)
                return

    def handle_data(self, data):
        if self.skip_depth:
            return
        hidden, fg, bg = self._state()
        hidden = hidden or (data.strip() != "" and _close(fg, bg))
        if self.anchor is not None and not hidden:
            self.anchor[1].append(data)
        self._out(data, hidden)


def _tidy(text: str, keep_lines: bool) -> str:
    if keep_lines:
        text = _SPACES.sub(" ", text)
        text = "\n".join(line.strip() for line in text.split("\n"))
        return _BLANK_LINES.sub("\n\n", text).strip()
    return re.sub(r"\s+", " ", text.replace("\u00a0", " ")).strip()


def _all_text(markup: str) -> str:
    """Every piece of text, tags dropped, for the hidden part of a result
    that could not be checked: nothing of it is given out as visible."""
    raw = re.sub(r"<!--.*?-->", " ", str(markup or ""), flags=re.S)
    raw = re.sub(r"<(style|script)\b[^>]*>.*?</\1\s*>", " ", raw, flags=re.I | re.S)
    return re.sub(r"<[^>]+>", " ", raw)


def visible_text(markup: str, keep_lines: bool = False) -> VisibleText:
    """What a reader of this HTML sees, and apart what is hidden."""
    markup = str(markup or "")
    try:
        # Styles first, wherever they are: comments are dropped, because
        # most clients do not apply a <style> inside one.
        sheets = _Sheets()
        sheets.feed(re.sub(r"<!--.*?-->", " ", markup, flags=re.S))
        sheets.close()
        rules, reason = _parse_sheet("\n".join(sheets.css))
        if sheets.external:
            reason = reason or "external style sheet (<link rel=stylesheet>)"
        parser = _Extractor(rules)
        parser.feed(markup)
        parser.close()
        visible, hidden = "".join(parser.visible), "".join(parser.hidden)
        links, seen = [], set()
        for text, url in parser.links:
            if url not in seen and len(links) < _MAX_LINKS:
                seen.add(url)
                links.append((text, url))
    except Exception as e:
        # Fail closed: nothing is handed out as visible, and the result
        # says it could not be checked.
        everything, _n = strip_invisible(_all_text(markup))
        return VisibleText(text="", hidden_text=_tidy(everything, False), invisible_chars=0,
                           hidden_markup_chars=len(re.sub(r"\s+", "", everything)),
                           checked=False, reason=f"parser error: {type(e).__name__}")
    smuggled = smuggled_ascii(visible) + " " + smuggled_ascii(hidden)
    visible, invisible = strip_invisible(visible)
    hidden, invisible_in_hidden = strip_invisible(hidden)
    return VisibleText(text=_tidy(visible, keep_lines),
                       hidden_text=_tidy(hidden + " " + smuggled, keep_lines=False),
                       invisible_chars=invisible,
                       hidden_markup_chars=len(re.sub(r"\s+", "", hidden)) + invisible_in_hidden,
                       checked=not reason, reason=reason, links=tuple(links))


def html_to_text(markup: str, keep_lines: bool = False) -> str:
    """The readable text of `markup` for a person (previews, alerts, search):
    no comments, styles, scripts, tags or hidden text, entities decoded.
    With keep_lines the paragraph breaks stay as newlines; otherwise
    everything collapses to one line. Text for an agent goes through
    read_mail(), which also withholds what could not be checked."""
    return visible_text(markup, keep_lines=keep_lines).text


@dataclass
class MailText:
    """A message as an agent may read it."""
    visible: str      # what may be handed to a model
    hidden: str       # what was hidden from the reader: for the injection check only
    hidden_chars: int
    checked: bool     # False: the body could not be evaluated, give the agent nothing
    reason: str = ""
    # When not checked: the best reading available, for a draft a person
    # reviews before it leaves (never for an agent that acts on its own).
    unverified: str = ""
    links: Tuple[Tuple[str, str], ...] = ()


def read_mail(message) -> MailText:
    """The visible and hidden text of a message dict as providers return it.

    An HTML body (Graph hands HTML, IMAP may) is read as a person sees it;
    a plain body loses its invisible characters, and the ASCII they may
    spell goes with the hidden part. When the HTML could not be checked,
    `visible` is empty and `checked` is False: the caller withholds the
    body, it does not fall back to a cruder reading."""
    if not isinstance(message, dict):
        return MailText("", "", 0, True)
    body = message.get("body")
    if isinstance(body, dict) and str(body.get("contentType") or "").lower() == "html":
        vt = visible_text(str(body.get("content") or ""), keep_lines=True)
        if not vt.checked:
            return MailText("", vt.hidden_text, vt.hidden_chars, False, vt.reason,
                            unverified=vt.text)
        return MailText(vt.text, vt.hidden_text, vt.hidden_chars, True, links=vt.links)
    raw = message.get("body_text")
    if not raw:
        raw = body.get("content") if isinstance(body, dict) else body
    raw = str(raw or "")
    text, invisible = strip_invisible(raw)
    return MailText(text, smuggled_ascii(raw), invisible, True)


def mail_texts(message) -> Tuple[str, str]:
    """(visible, hidden) text of a message: read_mail() without the verdict."""
    m = read_mail(message)
    return m.visible, m.hidden
