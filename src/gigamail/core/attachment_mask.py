# GigaMail — mail for your AI agent
# Copyright (C) 2026 Adecubed
# Licensed under the GNU AGPL v3 or later. See LICENSE.
"""Mask the text of a mail or an attachment before an agent reads it.

The same switch covers the body of a mail (read_message) and the text of
an attachment (read_attachment); the name of this module and of its
settings is older than the first.

An agent gets an attachment only through the read_attachment tool. With
the account's switch on, what the masker recognises (tax code, VAT
number, IBAN, email, phone, company name, plus the masks the user saved
for that account) is replaced by a placeholder before the text leaves
GigaMail. The switch is off by default and is set by the user (console);
no MCP tool can change it, so an agent cannot read in clear what the
user chose to hide.

Field rules cover what has no recognisable shape, such as a name on a
form: the user names the field as it is printed ("Full name") and says
what its value becomes: a placeholder, an invented name, or a fixed
text. The value is whatever follows the label on its line (or on the
next line when the label stands alone), and once found it is replaced
wherever it appears in that attachment.

Replacements are stable: the same value gives the same placeholder, or
the same invented name, in every attachment, so an agent reading a
hundred files can tell that two of them name the same person without
learning who. They are derived from the value with a secret kept on this
machine, so a placeholder cannot be checked against a guessed value.
Nothing maps a replacement back: this is one-way. Invented names are for
reading, not for counting: there are about 3.8 million of them, so two
people in a few hundred hardly ever share one, but it is not impossible
(about one chance in eight among a thousand people). Placeholders are
the ones to count with.

The same masking covers the prompts GigaMail writes itself with a mail's
text in them (the watcher's drafts, the follow-up after an appointment,
the console's draft button): see `for_agent`.

People's names are not recognised unless a field rule or a saved mask
covers them, and a scanned document has no text to mask (or to read).
"""
import hashlib
import hmac
import json
import re
import secrets
from typing import Dict, List, NamedTuple, Tuple

from gigamail.core import accounts, ade_masker

_ENABLED_KEY = "mask_attachments_account_{}"
_FIELDS_KEY = "mask_attachment_fields_account_{}"
_SECRET_KEY = "attachment_mask_secret"

_TYPES_KEY = "mask_types_account_{}"

# What the masker recognises by its shape (ade_masker's detector types).
# All of them are masked unless the user takes some out.
TYPES = ("CODICE_FISCALE", "PARTITA_IVA", "IBAN", "EMAIL", "TELEFONO", "AZIENDA")
ACTIONS = ("placeholder", "fake_name", "fixed")
MAX_RULES = 30
MAX_LABEL_CHARS = 80
MAX_FIXED_CHARS = 200
# A value this short ("B", "yes") is replaced only next to its label:
# everywhere else it is an ordinary word.
_MIN_CHARS_EVERYWHERE = 4

NOTE = (
    "Personal data in this text was replaced by placeholders such as "
    "[EMAIL_1a2b3c4d]: the user chose to mask what agents read. The same "
    "placeholder always stands for the same value, in every mail and "
    "attachment. "
    "The real values are not available to you: do not guess them, and "
    "refer to them by their placeholder."
)
NOTE_INVENTED = (
    "Some values, such as people's names, were replaced by invented ones: "
    "they are not real people. The same real value always gets the same "
    "invented one. Say so when you report them."
)

_FIRST_NAMES = (
    "Luca", "Anna", "Paolo", "Giulia", "Marco", "Sara", "Andrea", "Elena",
    "Davide", "Chiara", "Stefano", "Laura", "Matteo", "Silvia", "Simone",
    "Marta", "Fabio", "Irene", "Giorgio", "Alice", "Pietro", "Elisa",
    "Antonio", "Paola", "Roberto", "Lucia", "Enrico", "Monica", "Carlo",
    "Federica", "Alberto", "Valeria", "Franco", "Daniela", "Sergio",
    "Claudia", "Nicola", "Teresa", "Bruno", "Rita",
)
_LAST_NAMES = (
    "Bianchi", "Verdi", "Neri", "Gialli", "Bruni", "Fontana", "Colombo",
    "Marino", "Greco", "Conti", "Costa", "Gallo", "Mancini", "Rizzo",
    "Lombardi", "Moretti", "Barbieri", "Ferrara", "Santoro", "Marini",
    "Rinaldi", "Caruso", "Ferri", "Galli", "Martini", "Leone", "Longo",
    "Gentile", "Martinelli", "Vitale", "Serra", "Coppola", "De Santis",
    "Marchetti", "Parisi", "Villa", "Conte", "Ferraro", "Fabbri", "Pellegrini",
    "Palumbo", "Sanna", "Farina", "Monti", "Cattaneo", "Morelli", "Amato",
    "Silvestri", "Mazza", "Testa",
)


class Masked(NamedTuple):
    text: str
    hidden: int            # how many replacements were made
    invented: bool         # some of them are invented names
    unmatched: List[str]   # labels of field rules that found no value


def enabled(account_id) -> bool:
    """Whether attachments of this account are masked. Off unless the
    user switched it on; a setting that cannot be read masks, because
    the clear text of someone who asked for masking must not get out."""
    if account_id is None:
        return False
    try:
        value = accounts.get_setting(_ENABLED_KEY.format(int(account_id)), "0")
    except Exception:
        return True
    return str(value).strip() == "1"


def set_enabled(account_id: int, on: bool) -> bool:
    accounts.set_setting(_ENABLED_KEY.format(int(account_id)), "1" if on else "0")
    return bool(on)


# ── recognised types ─────────────────────────────────────────────────

def types(account_id) -> List[str]:
    """The recognised types this account masks: all of them unless the
    user took some out. A choice that cannot be read masks them all."""
    if account_id is None:
        return list(TYPES)
    try:
        raw = accounts.get_setting(_TYPES_KEY.format(int(account_id)), "") or ""
        if not str(raw).strip():
            return list(TYPES)
        chosen = json.loads(raw)
        if not isinstance(chosen, list):
            return list(TYPES)
    except Exception:
        return list(TYPES)
    return [t for t in TYPES if t in chosen]


def save_types(account_id: int, chosen) -> List[str]:
    if not isinstance(chosen, list) or any(t not in TYPES for t in chosen):
        raise ValueError("Unknown type to mask")
    kept = [t for t in TYPES if t in chosen]
    accounts.set_setting(_TYPES_KEY.format(int(account_id)), json.dumps(kept))
    return kept


# ── field rules ──────────────────────────────────────────────────────

def _clean_rules(rules) -> List[Dict[str, str]]:
    """The rules as stored: [{label, action, value}]. Raises ValueError
    on anything that is not a usable rule."""
    if not isinstance(rules, list):
        raise ValueError("Field rules must be a list")
    if len(rules) > MAX_RULES:
        raise ValueError(f"More than {MAX_RULES} field rules")
    out, seen = [], set()
    for rule in rules:
        if not isinstance(rule, dict):
            raise ValueError("A field rule must be an object")
        label = " ".join(str(rule.get("label") or "").split())
        if not label:
            raise ValueError("A field rule needs the label of the field")
        if len(label) > MAX_LABEL_CHARS:
            raise ValueError(f"Field label longer than {MAX_LABEL_CHARS} characters")
        if label.casefold() in seen:
            raise ValueError(f"Two rules for the field '{label}'")
        seen.add(label.casefold())
        action = str(rule.get("action") or "placeholder").strip()
        if action not in ACTIONS:
            raise ValueError(f"Unknown action '{action}'")
        value = ""
        if action == "fixed":
            value = " ".join(str(rule.get("value") or "").split())
            if not value:
                raise ValueError(f"The field '{label}' needs the text to put in its place")
            if len(value) > MAX_FIXED_CHARS:
                raise ValueError(f"Fixed text longer than {MAX_FIXED_CHARS} characters")
        out.append({"label": label, "action": action, "value": value})
    return out


def field_rules(account_id) -> List[Dict[str, str]]:
    """The account's field rules. Raises when they cannot be read: the
    caller must then not hand out the text those rules would have masked."""
    if account_id is None:
        return []
    raw = accounts.get_setting(_FIELDS_KEY.format(int(account_id)), "") or ""
    if not str(raw).strip():
        return []
    return _clean_rules(json.loads(raw))


def save_field_rules(account_id: int, rules) -> List[Dict[str, str]]:
    cleaned = _clean_rules(rules)
    accounts.set_setting(_FIELDS_KEY.format(int(account_id)), json.dumps(cleaned))
    return cleaned


# ── replacements ─────────────────────────────────────────────────────

def _secret() -> bytes:
    value = str(accounts.get_setting(_SECRET_KEY, "") or "").strip()
    if not value:
        value = secrets.token_hex(32)
        accounts.set_setting(_SECRET_KEY, value)
    return value.encode("ascii")


def _digest(key: bytes, value: str) -> str:
    # Spacing and case do not make a different person: "IT60 X054..." and
    # "it60x054..." are the same IBAN.
    norm = re.sub(r"\s+", "", value).casefold()
    return hmac.new(key, norm.encode("utf-8"), hashlib.sha256).hexdigest()


def _placeholder(key: bytes, prefix: str, value: str) -> str:
    label = re.sub(r"\s+", "_", str(prefix or "").strip().upper())
    label = re.sub(r"[^A-Z0-9_]", "", label) or "MASK"
    return f"[{label}_{_digest(key, value)[:8]}]"


def _fake_name(key: bytes, value: str) -> str:
    """Two first names and a double surname ("Luca Paolo Bianchi-Fontana").
    One of each gave 2,000 names: among a hundred people two of them
    shared one nine times out of ten, and an agent took them for the same
    person. Four parts give about 3.8 million."""
    n = int(_digest(key, value)[:16], 16)
    n, a = divmod(n, len(_FIRST_NAMES))
    n, b = divmod(n, len(_FIRST_NAMES) - 1)
    n, c = divmod(n, len(_LAST_NAMES))
    n, d = divmod(n, len(_LAST_NAMES) - 1)
    first, last = _FIRST_NAMES[a], _LAST_NAMES[c]
    second = [name for name in _FIRST_NAMES if name != first][b]
    other = [name for name in _LAST_NAMES if name != last][d]
    return f"{first} {second} {last}-{other}"


def _replacement(key: bytes, rule: Dict[str, str], value: str) -> str:
    if rule["action"] == "fixed":
        return rule["value"]
    if rule["action"] == "fake_name":
        return _fake_name(key, value)
    return _placeholder(key, rule["label"], value)


def _spaced(text: str) -> str:
    """`text` as a pattern that does not mind how its words are spaced."""
    return r"[ \t]+".join(re.escape(word) for word in text.split())


def _values_after_labels(text: str, rules) -> Tuple[list, List[str]]:
    """For each rule, the value printed after its label: on the same line,
    or on the next one when the label stands alone.
    ([(start, end, rule)], [labels not found])."""
    found, unmatched, claimed = [], [], []
    # Longest label first: "Name" must not take the line of "Name and
    # surname" and call "and surname ..." its value.
    for rule in sorted(rules, key=lambda r: len(r["label"]), reverse=True):
        pattern = re.compile(
            r"^[ \t]*" + _spaced(rule["label"]) + r"(?!\w)[ \t]*[:=\-]?[ \t]*"
            r"(?:(?P<same>\S[^\n]*)|\r?\n[ \t]*(?P<next>\S[^\n]*))",
            re.IGNORECASE | re.MULTILINE)
        hit = False
        for m in pattern.finditer(text):
            if any(m.start() < e and m.end() > s for s, e in claimed):
                continue
            group = "same" if m.group("same") is not None else "next"
            value = m.group(group).rstrip()
            if not value:
                continue
            start = m.start(group)
            claimed.append((m.start(), m.end()))
            found.append((start, start + len(value), rule))
            hit = True
        if not hit:
            unmatched.append(rule["label"])
    return found, unmatched


def apply(account_id, text: str) -> Masked:
    """`text` as the agent may read it. Raises if the rules cannot be
    read or the masker fails; the caller must not fall back to `text`."""
    rules = field_rules(account_id)
    if not text:
        return Masked(text or "", 0, False, [r["label"] for r in rules])
    key = _secret()
    spans = []            # (start, end, replacement, invented)

    def free(start, end):
        return not any(start < e and end > s for s, e, _r, _i in spans)

    by_label, unmatched = _values_after_labels(text, rules)
    values = {}           # normalised value -> (value, rule)
    for start, end, rule in by_label:
        value = text[start:end]
        if free(start, end):
            spans.append((start, end, _replacement(key, rule, value),
                          rule["action"] == "fake_name"))
        values.setdefault(re.sub(r"\s+", "", value).casefold(), (value, rule))
    # The same value elsewhere in the attachment (a signature at the
    # bottom) is the same person.
    for value, rule in sorted(values.values(), key=lambda v: len(v[0]), reverse=True):
        if len(re.sub(r"\s+", "", value)) < _MIN_CHARS_EVERYWHERE:
            continue
        again = re.compile(r"(?<!\w)" + _spaced(value) + r"(?!\w)", re.IGNORECASE)
        for m in again.finditer(text):
            if free(m.start(), m.end()):
                spans.append((m.start(), m.end(), _replacement(key, rule, value),
                              rule["action"] == "fake_name"))

    user_masks = ade_masker.get_user_masks(int(account_id)) if account_id else []
    wanted = set(types(account_id))
    for item in ade_masker.detect(text, user_masks=user_masks):
        # A type the user took out stays in clear; the masks they saved
        # themselves are always applied.
        if item.get("source") == "validator" and item["type"] not in wanted:
            continue
        start, end = item["start"], item["end"]
        raw = text[start:end]
        # A match can carry the blank around it: keep the layout.
        start += len(raw) - len(raw.lstrip())
        end -= len(raw) - len(raw.rstrip())
        if end > start and free(start, end):
            spans.append((start, end,
                          _placeholder(key, item["label_prefix"], text[start:end]), False))

    if not spans:
        return Masked(text, 0, False, unmatched)
    out, pos = [], 0
    for start, end, replacement, _invented in sorted(spans):
        out.append(text[pos:start])
        out.append(replacement)
        pos = end
    out.append(text[pos:])
    return Masked("".join(out), len(spans), any(s[3] for s in spans), unmatched)


def mask(account_id, text: str) -> Tuple[str, int]:
    """(masked text, how many replacements). See `apply`."""
    result = apply(account_id, text)
    return result.text, result.hidden


def for_agent(account_id, text: str) -> Tuple[str, str]:
    """`text` as it may go into a prompt GigaMail writes itself, and the
    note that must go with it. While the account's switch is off: the text
    as it is, and no note. Raises like `apply` when the masking fails; the
    caller must then leave the text out, never fall back to it."""
    if not enabled(account_id):
        return text, ""
    result = apply(account_id, text)
    notes = []
    if result.hidden:
        notes.append(NOTE)
    if result.invented:
        notes.append(NOTE_INVENTED)
    return result.text, " ".join(notes)
