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
module returns the visible text and, apart, what was hidden, so callers
can tell the agent that something was left out.

Declared limit: it reads inline styles, `hidden`, <font color>, bgcolor
and simple class or id rules in <style> blocks (outside @media). Rules
with descendant selectors, external style sheets and colours close to the
background but not near enough are not seen. It narrows the gap between
what the person sees and what the agent reads; it does not close it.
"""
import html
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Dict, List, Optional, Set, Tuple

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


@dataclass
class VisibleText:
    text: str
    hidden_text: str
    invisible_chars: int
    hidden_markup_chars: int = 0

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


def _colour(value: str) -> Optional[Tuple[int, ...]]:
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
    m = re.fullmatch(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([\d.]+)\s*)?\)", v)
    if m:
        if m.group(4) is not None and float(m.group(4)) < 0.1:
            return ()
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


def _style(value: str) -> Dict[str, str]:
    out = {}
    for decl in (value or "").split(";"):
        if ":" in decl:
            k, v = decl.split(":", 1)
            out[k.strip().lower()] = v.replace("!important", "").strip().lower()
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


def _rules(css: str) -> Tuple[Set[str], Set[str]]:
    """Classes and ids hidden by simple rules of a <style> block. Rules
    inside @media apply only to some screens and are left out."""
    css = re.sub(r"/\*.*?\*/", "", css or "", flags=re.S)
    # drop @media / @supports blocks, nested braces included
    out, depth, i = [], 0, 0
    while i < len(css):
        if depth == 0 and css.startswith("@", i):
            j = css.find("{", i)
            k = css.find(";", i)
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
    classes, ids = set(), set()
    for selectors, body in re.findall(r"([^{}]+)\{([^{}]*)\}", "".join(out)):
        if not _hides(_style(body)):
            continue
        for sel in selectors.split(","):
            sel = sel.strip()
            if not sel or re.search(r"[\s>+~:\[]", sel):
                continue   # only simple selectors: tag.class, .class, #id
            classes.update(re.findall(r"\.([\w-]+)", sel))
            ids.update(re.findall(r"#([\w-]+)", sel))
    return classes, ids


class _Extractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        # each open element: (tag, hidden, foreground, background)
        self.stack: List[Tuple[str, bool, Tuple[int, ...], Tuple[int, ...]]] = []
        self.skip_depth = 0
        self.style_text: List[str] = []
        self.in_style = False
        self.hidden_classes: Set[str] = set()
        self.hidden_ids: Set[str] = set()
        self.visible: List[str] = []
        self.hidden: List[str] = []

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
            if tag == "style" and not self.skip_depth:
                self.in_style = True
            self.skip_depth += 1
            return
        if self.skip_depth:
            return
        hidden, fg, bg = self._state()
        a = {k.lower(): (v or "") for k, v in attrs}
        props = _style(a.get("style", ""))
        classes = set(a.get("class", "").split())
        if ("hidden" in a or _hides(props)
                or classes & self.hidden_classes or a.get("id", "") in self.hidden_ids
                or (tag == "input" and a.get("type", "").lower() == "hidden")):
            hidden = True
        new_bg = _first_colour(props.get("background-color", "")) \
            or _first_colour(props.get("background", "")) or _colour(a.get("bgcolor", ""))
        if new_bg:
            bg = new_bg
        new_fg = _colour(props.get("color", "")) or (_colour(a.get("color", "")) if tag == "font" else None)
        if new_fg:
            fg = new_fg
        # The colour test runs on the text itself (handle_data): a dark
        # cell is not hidden, only text the colour of its background is.
        if tag == "br":
            self._out("\n", hidden)
        elif tag not in _VOID:
            self.stack.append((tag, hidden, fg, bg))
        self._out(" ", hidden)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        tag = tag.lower()
        if tag not in _VOID and tag not in _SKIPPED:
            self.handle_endtag(tag)
        elif tag in _SKIPPED and self.skip_depth:
            self.skip_depth -= 1
            self.in_style = False

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in _SKIPPED:
            if self.skip_depth:
                self.skip_depth -= 1
                if tag == "style" and self.in_style and not self.skip_depth:
                    self.in_style = False
                    classes, ids = _rules("".join(self.style_text))
                    self.hidden_classes |= classes
                    self.hidden_ids |= ids
                    self.style_text = []
            return
        if self.skip_depth:
            return
        hidden = self._state()[0]
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                hidden = self.stack[i][1]
                del self.stack[i:]
                break
        else:
            return
        self._out("\n" if tag in _BREAK_AFTER else " ", hidden)

    def handle_data(self, data):
        if self.in_style:
            self.style_text.append(data)
            return
        if self.skip_depth:
            return
        hidden, fg, bg = self._state()
        self._out(data, hidden or (data.strip() != "" and _close(fg, bg)))


def _tidy(text: str, keep_lines: bool) -> str:
    if keep_lines:
        text = _SPACES.sub(" ", text)
        text = "\n".join(line.strip() for line in text.split("\n"))
        return _BLANK_LINES.sub("\n\n", text).strip()
    return re.sub(r"\s+", " ", text.replace("\u00a0", " ")).strip()


def visible_text(markup: str, keep_lines: bool = False) -> VisibleText:
    """What a reader of this HTML sees, and apart what is hidden."""
    parser = _Extractor()
    try:
        parser.feed(str(markup or ""))
        parser.close()
        visible, hidden = "".join(parser.visible), "".join(parser.hidden)
    except Exception:
        # A parser failure must not hand out the raw markup: fall back to
        # dropping every tag, comment and skipped block.
        raw = re.sub(r"<!--.*?-->", " ", str(markup or ""), flags=re.S)
        raw = re.sub(r"<(head|style|script|title|xml)\b[^>]*>.*?</\1\s*>", " ", raw,
                     flags=re.I | re.S)
        visible, hidden = html.unescape(re.sub(r"<[^>]+>", " ", raw)), ""
    smuggled = smuggled_ascii(visible) + " " + smuggled_ascii(hidden)
    visible, invisible = strip_invisible(visible)
    hidden, invisible_in_hidden = strip_invisible(hidden)
    markup_chars = len(re.sub(r"\s+", "", hidden)) + invisible_in_hidden
    return VisibleText(text=_tidy(visible, keep_lines),
                       hidden_text=_tidy(hidden + " " + smuggled, keep_lines=False),
                       invisible_chars=invisible,
                       hidden_markup_chars=markup_chars)


def html_to_text(markup: str, keep_lines: bool = False) -> str:
    """The readable text of `markup`: no comments, styles, scripts, tags
    or hidden text, entities decoded. With keep_lines the paragraph breaks
    stay as newlines; otherwise everything collapses to one line."""
    return visible_text(markup, keep_lines=keep_lines).text


def mail_texts(message) -> Tuple[str, str]:
    """(visible, hidden) text of a message dict as the providers return it.

    An HTML body (Graph hands HTML, IMAP may) is read as a person sees it;
    a plain body loses its invisible characters, and the ASCII they may
    spell goes with the hidden part. The visible part is what a model may
    read; the hidden part is for the injection check only."""
    if not isinstance(message, dict):
        return "", ""
    body = message.get("body")
    if isinstance(body, dict) and str(body.get("contentType") or "").lower() == "html":
        vt = visible_text(str(body.get("content") or ""), keep_lines=True)
        return vt.text, vt.hidden_text
    raw = message.get("body_text")
    if not raw:
        raw = body.get("content") if isinstance(body, dict) else body
    raw = str(raw or "")
    return strip_invisible(raw)[0], smuggled_ascii(raw)
