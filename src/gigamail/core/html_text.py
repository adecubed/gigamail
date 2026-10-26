"""Plain text from a mail's HTML, for previews and alerts.

Stripping tags alone is not enough for mail written in Outlook: its HTML
carries a <style> block inside conditional comments
(<!--[if !mso]><style>v\\:* {behavior:url(#default#VML);} ...</style><![endif]-->),
and once the tags are gone the CSS rules stay in the text. The list
preview and the Telegram alert then opened with "v\\:* {behavior:..." and
with raw entities such as &nbsp;.
"""
import html
import re

_COMMENTS = re.compile(r"<!--.*?-->", re.DOTALL)
_HIDDEN_BLOCKS = re.compile(r"<(head|style|script|title|xml)\b[^>]*>.*?</\1\s*>",
                            re.IGNORECASE | re.DOTALL)
_BREAKS = re.compile(r"<br\s*/?>|</(p|div|tr|li|h[1-6])\s*>", re.IGNORECASE)
_TAGS = re.compile(r"<[^>]+>")
_SPACES = re.compile(r"[ \t\r\f\v ]+")
_BLANK_LINES = re.compile(r"\n\s*\n+")


def html_to_text(markup: str, keep_lines: bool = False) -> str:
    """The readable text of `markup`: no comments, styles, scripts or tags,
    entities decoded. With keep_lines the paragraph breaks stay as
    newlines; otherwise everything collapses to one line."""
    text = _COMMENTS.sub(" ", str(markup or ""))
    text = _HIDDEN_BLOCKS.sub(" ", text)
    text = _BREAKS.sub("\n", text)
    text = _TAGS.sub(" ", text)
    text = html.unescape(text)
    if keep_lines:
        text = _SPACES.sub(" ", text)
        return _BLANK_LINES.sub("\n\n", text).strip()
    return re.sub(r"\s+", " ", text.replace(" ", " ")).strip()
