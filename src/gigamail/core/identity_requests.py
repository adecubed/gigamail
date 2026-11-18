"""Validation and approval preview of a request to change the identity
texts of an account (the `update_identity` tool).

The texts come from the agent, so they are untrusted: `clean` refuses what
the approval text could not show as it is, and `preview` shows every line of
every value, quoted, whole: nothing is cut, and nothing the agent writes can
pass for the structure of the preview."""
from typing import Any, Dict, List

from gigamail.core.rule_requests import BLOCK_PREFIX, bad_char, say, shown

TEXT_FIELDS = ("who_am_i", "what_i_do", "tone", "key_info")
AGENT_MAX_FIELD = 4000
AGENT_MAX_FIELD_LINES = 120


def clean(fields: Dict[str, Any]) -> Dict[str, str]:
    """The given fields, checked and normalised. None values are dropped;
    ValueError names the field and the limit otherwise."""
    out: Dict[str, str] = {}
    for key, value in fields.items():
        if key not in TEXT_FIELDS:
            raise ValueError(f"{key}: not an editable identity field "
                             f"(editable: {', '.join(TEXT_FIELDS)})")
        if value is None:
            continue
        if not isinstance(value, str):
            raise ValueError(f"{key}: must be text")
        text = _lines(value)
        # Before the strip: a trailing U+2028 or \x0b is whitespace to rstrip,
        # and must be refused, not trimmed away.
        if any(bad_char(ch) and ch not in "\n\t" for ch in text):
            raise ValueError(f"{key}: no control characters other than newline and tab, "
                             "no line or paragraph separators, no bidirectional controls, "
                             "no invisible format characters")
        text = text.rstrip()
        if len(text) > AGENT_MAX_FIELD:
            raise ValueError(f"{key}: at most {AGENT_MAX_FIELD} characters are allowed "
                             f"(got {len(text)})")
        if len(text.split("\n")) > AGENT_MAX_FIELD_LINES:
            raise ValueError(f"{key}: at most {AGENT_MAX_FIELD_LINES} lines are allowed "
                             f"(got {len(text.split(chr(10)))})")
        out[key] = text
    return out


def _lines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _shown(text: str) -> str:
    """A value as the preview may show it. The "before" text comes from
    storage and was never validated here (rule_requests.shown)."""
    return shown(text or "")


def changes(current: Dict[str, Any], cleaned: Dict[str, str]) -> Dict[str, str]:
    """The cleaned fields whose value differs from the current one, the
    stored value normalised as `clean` normalises (line endings, trailing
    whitespace): a stored "warm\\r\\n" is the same as "warm"."""
    return {k: v for k, v in cleaned.items()
            if v != _lines(str(current.get(k) or "")).rstrip()}


def snapshot(identity: Dict[str, Any]) -> Dict[str, str]:
    return {k: identity.get(k) or "" for k in TEXT_FIELDS}


def _labels() -> Dict[str, str]:
    return {
        "who_am_i": say("Chi sono", "Who I am"),
        "what_i_do": say("Cosa faccio", "What I do"),
        "tone": say("Tono", "Tone"),
        "key_info": say("Informazioni chiave", "Key information"),
    }


def _block(label: str, text: str) -> List[str]:
    """The label, then every line of the value behind the quoting prefix.
    An empty value is said on the label line, outside the quoting: a value
    that reads "(empty)" is quoted, so the two cannot be mistaken."""
    text = _shown(text)
    if not text.strip():
        return [f"{label}: " + say("(vuoto)", "(empty)")]
    return [f"{label}:"] + [BLOCK_PREFIX + line for line in text.split("\n")]


def preview(changed: Dict[str, str], before: Dict[str, Any], *, account_id: int,
            account_label: str = "") -> Dict[str, Any]:
    labels = _labels()
    fields = [f for f in TEXT_FIELDS if f in changed]
    # One line, as rule_requests shows a value in a title.
    who = _shown(" ".join((account_label or "").split())) or f"account {account_id}"
    title = say(f"Modifica l'identità di {who}", f"Change the identity of {who}")
    title += " [" + ", ".join(labels[f] for f in fields) + "]"
    lines: List[str] = []
    for f in fields:
        lines.append(labels[f])
        lines.extend(_block(say("Prima", "Before"), before.get(f) or ""))
        lines.extend(_block(say("Dopo", "After"), changed[f]))
    rest = [labels[f] for f in TEXT_FIELDS if f not in changed]
    if rest:
        lines.append(say("Restano come sono: ", "Unchanged: ") + ", ".join(rest))
    return {"action": "identity_update", "subject": title, "body": "\n".join(lines),
            "account_id": account_id}
