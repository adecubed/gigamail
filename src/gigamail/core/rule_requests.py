"""Validation of reply-rule requests, shared by the console and the agent tools.

Both callers hand in raw fields and get back clean ones, or a ValueError
with the reason. The existing (Italian) error texts are the console's and
stay as they are.
"""
import os
import re
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

from gigamail.core import attachments, mail_guard
from gigamail.core import rules as rules_mod

CREATE_FIELDS = ("trigger_kind", "trigger_values", "reply_style", "doc_paths",
                 "mode", "first_contact", "daily_cap", "cooldown_hours",
                 "expiry_days", "cc", "attachments")
UPDATE_FIELDS = ("trigger_kind", "trigger_values", "reply_style", "doc_paths",
                 "mode", "first_contact", "daily_cap", "cooldown_hours",
                 "cc", "attachments")

_WINDOWS_SYSTEM_VARS = ("SystemRoot", "ProgramFiles", "ProgramFiles(x86)", "ProgramData")
# /private: on macOS realpath turns /etc and /var into /private/etc and
# /private/var.
_POSIX_SYSTEM_DIRS = ("/etc", "/usr", "/bin", "/sbin", "/var", "/private", "/System",
                      "/Library")


def _clean_trigger(kind: str, values: List[str]) -> List[str]:
    return [v.strip().lower() if kind == "senders" else v.strip()
            for v in values or [] if v and v.strip()]


def _clean_list(values: List[str]) -> List[str]:
    return [v.strip() for v in values or [] if v and v.strip()]


def _system_dirs() -> List[str]:
    """System folders, from the environment only (no disk access)."""
    if os.name == "nt":
        found = (os.environ.get(v) for v in _WINDOWS_SYSTEM_VARS)
        return [os.path.normcase(os.path.normpath(p)) for p in found if p]
    return list(_POSIX_SYSTEM_DIRS)


def _under(norm: str, root: str, sep: str) -> bool:
    return norm == root or norm.startswith(root.rstrip(sep) + sep)


def folder_reason(real: str, pathmod, roots, home: str) -> str:
    """Why `real` sits in a system folder or in the Library folder right
    under the user's home (macOS keeps Mail, Messages and the Keychains
    there), or "". `pathmod` is ntpath or posixpath: the rule is pure, so a
    test can run the POSIX shape on Windows. On POSIX the comparison ignores
    case, as the default macOS disk does."""
    def norm(p: str) -> str:
        n = pathmod.normcase(pathmod.normpath(p))
        return n if pathmod.sep == "\\" else n.lower()
    sep = pathmod.sep
    target = norm(real)
    for root in roots:
        if _under(target, norm(root), sep):
            return f"{real} (a system folder is not allowed)"
    if home:
        if _under(target, norm(pathmod.join(home, "Library")), sep):
            return f"{real} (the Library folder in your home is not allowed)"
    return ""


def excluded_reason(real: str) -> str:
    """Why a resolved absolute path is not allowed as a document, or "" when
    it is. Looks only at the string and the environment, never at the disk.
    A path component starting with a dot (a file named that way included),
    AppData in any case, the system folders and ~/Library are refused."""
    for part in re.split(r"[\\/]+", real):
        if part.startswith(".") and part not in (".", ".."):
            return f"{real} (a folder or file starting with a dot is not allowed)"
        if part.lower() == "appdata":
            return f"{real} (the AppData folder is not allowed)"
    return folder_reason(real, os.path, _system_dirs(), os.path.expanduser("~"))


def _checked_doc(path: str) -> Tuple[bool, str, str]:
    """(ok, why, the resolved real path that was checked)."""
    raw = str(path or "").strip()
    # Before anything touches the disk: looking at a path on another machine
    # already makes Windows sign in to it.
    if attachments.is_network_path(raw):
        return False, f"{raw} (a document on a network path is not allowed)", ""
    real = os.path.realpath(raw)
    # A local link can point at a share: refuse what it resolves to.
    if attachments.is_network_path(real):
        return False, f"{raw} (a document on a network path is not allowed)", real
    if mail_guard.is_executable_name(os.path.basename(real)):
        return False, f"{raw} (a program is not a document)", real
    if attachments.is_gigamail_data(real):
        return False, f"{raw} (GigaMail's own data is not a document)", real
    why = excluded_reason(real)
    return (False, why, real) if why else (True, "", real)


def is_allowed_doc(path: str) -> Tuple[bool, str]:
    """(True, "") or (False, why) for a path offered as a rule document."""
    ok, why, _real = _checked_doc(path)
    return ok, why


def clean_docs(account_id: int, docs: List[str], *, guard: bool) -> List[str]:
    """Absolute paths of existing documents. With guard, an item that is not
    a path is the name of a knowledge file, and a path must pass
    is_allowed_doc and is stored as the real path that was checked (a link
    is not followed again later, to somewhere else)."""
    out = []
    for item in docs or []:
        item = str(item or "").strip()
        if not item:
            continue
        if guard and not attachments.is_path(item):
            resolved, missing = attachments.resolve(account_id, [item])
            if missing or not resolved:
                raise ValueError(f"no such document: {item}")
            pth = os.path.abspath(resolved[0]["path"])
        elif guard:
            ok, why, pth = _checked_doc(item)
            if not ok:
                raise ValueError(why)
        else:
            pth = os.path.abspath(item)
        if not os.path.exists(pth):
            raise ValueError(f"no such document: {pth}" if guard
                             else f"Documento inesistente: {pth}")
        out.append(pth)
    return out


def _clean_attachments(account_id: int, names: List[str]) -> List[str]:
    """Fixed attachments are names of files registered in the identity:
    a name that resolves to nothing is refused now, not discovered in a
    month when the rule fires and the mail goes without it."""
    names = _clean_list(names)
    if not names:
        return []
    _resolved, missing = attachments.resolve(account_id, names)
    if missing:
        raise ValueError("Allegati non registrati nell'identity: " + ", ".join(missing))
    return names


def clean_create(account_id: int, fields: Dict[str, Any], *,
                 guard_docs: bool = False) -> Dict[str, Any]:
    """Clean fields ready for RuleStore.create (no account_id, created_by or
    hello_verified_at). Unknown keys are dropped."""
    f = {k: v for k, v in fields.items() if k in CREATE_FIELDS and v is not None}
    f.setdefault("reply_style", "")
    f.setdefault("mode", "semi")
    f.setdefault("first_contact", "semi")
    f.setdefault("daily_cap", rules_mod.DEFAULT_DAILY_CAP)
    f.setdefault("cooldown_hours", float(rules_mod.DEFAULT_COOLDOWN_HOURS))
    f.setdefault("expiry_days", float(rules_mod.DEFAULT_EXPIRY_DAYS))
    kind = f.get("trigger_kind")
    if kind not in rules_mod.TRIGGER_KINDS:
        raise ValueError("trigger_kind non valido")
    if f["mode"] not in rules_mod.MODES or f["first_contact"] not in rules_mod.MODES:
        raise ValueError("mode/first_contact non validi")
    f["trigger_values"] = _clean_trigger(kind, f.get("trigger_values"))
    if not f["trigger_values"]:
        raise ValueError("trigger vuoto")
    f["doc_paths"] = clean_docs(account_id, f.get("doc_paths") or [], guard=guard_docs)
    f["attachments"] = _clean_attachments(account_id, f.get("attachments") or [])
    f["cc"] = _clean_list(f.get("cc") or [])
    return f


def clean_update(rule: Dict[str, Any], fields: Dict[str, Any], *,
                 guard_docs: bool = False) -> Dict[str, Any]:
    """Only the fields sent (not None), cleaned. ValueError("nothing to
    change") when none."""
    f = {k: v for k, v in fields.items() if k in UPDATE_FIELDS and v is not None}
    if not f:
        raise ValueError("nothing to change")
    kind = f.get("trigger_kind", rule["trigger_kind"])
    if kind not in rules_mod.TRIGGER_KINDS:
        raise ValueError("trigger_kind non valido")
    if "trigger_values" in f or "trigger_kind" in f:
        f["trigger_kind"] = kind
        f["trigger_values"] = _clean_trigger(
            kind, f.get("trigger_values", rule["trigger_values"]))
        if not f["trigger_values"]:
            raise ValueError("trigger vuoto")
    for key in ("mode", "first_contact"):
        if f.get(key, "semi") not in rules_mod.MODES:
            raise ValueError("mode/first_contact non validi")
    if "doc_paths" in f:
        f["doc_paths"] = clean_docs(rule["account_id"], f["doc_paths"], guard=guard_docs)
    if "attachments" in f:
        f["attachments"] = _clean_attachments(rule["account_id"], f["attachments"])
    if "cc" in f:
        f["cc"] = _clean_list(f["cc"])
    return f


# Limits for requests made through the agent tools. The console keeps none:
# a person fills a form, an agent can be talked into a very long one.
AGENT_LIMITS = {"trigger_values": 50, "cc": 10, "doc_paths": 20, "attachments": 20}
AGENT_MAX_INSTRUCTION = 2000
AGENT_MAX_INSTRUCTION_LINES = 60
# All the list items of one request together, measured on what is stored
# (a document as its resolved path). It bounds what the agent can ask for:
# the approval text of the largest request, before and after included,
# stays a few screens long (tests/test_rule_requests.py measures it). Every
# channel still shows a rule request whole, whatever its length.
AGENT_MAX_LIST_CHARS = 6000


def normalize_instruction(text: Any) -> Any:
    """Windows line endings in an instruction become plain newlines, before
    it is checked and stored."""
    if not isinstance(text, str):
        return text
    return text.replace("\r\n", "\n").replace("\r", "\n")


def bad_char(ch: str) -> bool:
    """A control character, a line or paragraph separator, a bidirectional
    control, or an invisible format character: what the display strips,
    breaks on or does not show, while a model reading the text still does.
    Format characters (category Cf, the tag characters among them) are
    refused except the zero-width non-joiner and joiner, which emoji
    sequences and some scripts need; so are the variation selectors
    supplement (U+E0100-U+E01EF), but not U+FE00-U+FE0F (emoji
    presentation)."""
    cp = ord(ch)
    category = unicodedata.category(ch)
    return (category == "Cc" or ch in "\u2028\u2029" or cp in BIDI
            or (category == "Cf" and cp not in _JOINERS)
            or 0xE0100 <= cp <= 0xE01EF)


_JOINERS = (0x200C, 0x200D)


def shown(text: str) -> str:
    """Text as a preview may show it, whatever it holds (a stored value is
    never validated): line endings become \\n, and every other character
    bad_char refuses, except \\n and \\t, a visible U+FFFD."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return "".join("\ufffd" if bad_char(ch) and ch not in "\n\t" else ch for ch in text)


def _check_item(key: str, item: Any, one_address: bool) -> None:
    text = str(item)
    if len(text) > _VALUE_MAX and key == "doc_paths":
        raise ValueError(f"doc_paths: the resolved path of a document is too long to be "
                         f"shown whole: {len(text)} characters, at most {_VALUE_MAX} "
                         f"({_one(text)})")
    if len(text) > _VALUE_MAX:
        raise ValueError(f"{key}: an item is at most {_VALUE_MAX} characters long "
                         f"(got {len(text)})")
    if any(bad_char(ch) for ch in text):
        raise ValueError(f"{key}: an item cannot contain control characters, line "
                         "breaks, bidirectional controls or invisible format characters")
    inner = text.strip()
    if one_address and (any(ch.isspace() for ch in inner) or "," in inner):
        raise ValueError(f"{key}: one address per item, without spaces or commas")
    if " ".join(inner.split()) != inner:
        raise ValueError(f"{key}: an item cannot contain whitespace other than single spaces")


def check_agent_counts(fields: Dict[str, Any]) -> None:
    """The item counts only, on the raw request: cheap, and done before the
    cleaning touches the disk once per document."""
    for key, limit in AGENT_LIMITS.items():
        value = fields.get(key)
        if value is not None and len(value) > limit:
            raise ValueError(f"{key}: at most {limit} items are allowed (got {len(value)})")


def check_agent_limits(fields: Dict[str, Any], kind: Optional[str] = None) -> None:
    """ValueError naming the field when a request made by the agent is
    larger than allowed or holds what the approval text could not show as
    it is. Run on the CLEANED fields, the ones that are stored and shown (a
    document as its resolved path). Looks only at the fields present.
    `kind` is the rule's trigger kind when the request does not change it."""
    kind = fields.get("trigger_kind") or kind
    check_agent_counts(fields)
    total = 0
    for key in AGENT_LIMITS:
        value = fields.get(key)
        if value is None:
            continue
        one_address = key == "cc" or (key == "trigger_values" and kind != "folder")
        for item in value:
            _check_item(key, item, one_address)
            total += len(str(item))
    if total > AGENT_MAX_LIST_CHARS:
        raise ValueError(f"trigger_values, cc, doc_paths, attachments: at most "
                         f"{AGENT_MAX_LIST_CHARS} characters in all (got {total})")
    style = fields.get("reply_style")
    if style is None:
        return
    if len(style) > AGENT_MAX_INSTRUCTION:
        raise ValueError(f"reply_style: at most {AGENT_MAX_INSTRUCTION} characters are "
                         f"allowed (got {len(style)})")
    if len(style.splitlines()) > AGENT_MAX_INSTRUCTION_LINES:
        raise ValueError(f"reply_style: at most {AGENT_MAX_INSTRUCTION_LINES} lines are "
                         f"allowed (got {len(style.splitlines())})")
    if any(bad_char(ch) and ch not in "\n\t" for ch in style):
        raise ValueError("reply_style: no control characters other than newline and tab, "
                         "no bidirectional controls and no invisible format characters")


# --- previews: what the user reads before approving a request ---------------
#
# Every value comes from the agent, so it is untrusted text. Single-line
# values are collapsed to one line, capped and stripped of bidirectional
# controls. The text is laid out so that nothing the agent writes can look
# like a field or push a field out of a notification that truncates the body:
# fixed-size lines first, then the lists (one prefixed item per line, none
# ever hidden), then the free-text instruction as a quoted block.

ACTIONS = ("create", "update", "resume", "renew", "delete")
_VALUE_MAX = 200
BLOCK_PREFIX = "  │ "
_ITEM_PREFIX = "  • "
BIDI = dict.fromkeys(
    [*range(0x202A, 0x202F), *range(0x2066, 0x206A), 0x200E, 0x200F, 0x061C])


def say(it: str, en: str) -> str:
    from gigamail import policy  # lazy: policy must not end up importing this module
    return it if policy.user_lang() == "it" else en


def _num(value: Any) -> str:
    """10 and not 10.0 for a whole value."""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _one(value: Any) -> str:
    """One line, every hidden or control character shown as U+FFFD, at
    most _VALUE_MAX characters."""
    # Marked before the whitespace is collapsed: str.split would turn a
    # separator such as U+2028 or  into a plain space.
    text = " ".join(shown(str(value)).split())
    return text if len(text) <= _VALUE_MAX else text[:_VALUE_MAX - 1] + "…"


def _block(label: str, text: Any) -> List[str]:
    """A free-text value as a label line and its lines, each visibly quoted."""
    text = shown(str(text or ""))
    if not text.strip():
        return [f"{label}: {say('(nessuna)', '(none)')}"]
    return [f"{label}:"] + [BLOCK_PREFIX + line for line in text.rstrip("\n").split("\n")]


def _as_list(value: Any) -> List[str]:
    """The display items of a value that should be a list: a str is one item,
    None is empty, a list or tuple is its items, a set its items in sorted
    order (the same text every time), anything else is one item. None items
    and items that are empty once collapsed are dropped."""
    if value is None:
        raw: List[Any] = []
    elif isinstance(value, (set, frozenset)):
        raw = sorted(value, key=str)
    elif isinstance(value, (list, tuple)):
        raw = list(value)
    else:
        raw = [value]
    return [one for one in (_one(v) for v in raw if v is not None) if one]


def _items(label: str, values: Any) -> List[str]:
    """A list: the label, then one prefixed item per line. Empty stays on the
    label's line."""
    items = _as_list(values)
    if not items:
        return [f"{label}: {say('(nessuno)', '(none)')}"]
    return [f"{label}:"] + [_ITEM_PREFIX + v for v in items]


def _mode_text(mode: Any) -> str:
    if mode == "auto":
        return say("AUTO — risponde da sola, senza chiederti",
                    "AUTO — replies on its own, without asking you")
    if mode == "semi":
        return say("SEMI — prepara la risposta e aspetta la tua approvazione",
                    "SEMI — prepares the reply and waits for your approval")
    return _one(mode)


def _account_line(account_label: str, *sources: Dict[str, Any]) -> List[str]:
    if account_label:
        return [f"Account: {_one(account_label)}"]
    for src in sources:
        if src.get("account_id") is not None:
            return [f"Account: #{_one(src['account_id'])}"]
    return []


def _unit(key: str) -> str:
    if key == "cooldown_hours":
        return " " + say("ore", "hours")
    if key == "expiry_days":
        return " " + say("giorni", "days")
    return ""


def _scalar(key: str, value: Any) -> str:
    """A one-line value as shown in a before -> after line."""
    if value in ("", None):
        return say("(nessuna)", "(none)")
    return _one(_num(value)) + _unit(key)


def _scalar_labels() -> Dict[str, str]:
    """One-line fields, in display order."""
    return {
        "trigger_kind": say("Tipo di regola", "Rule type"),
        "mode": say("Modalità", "Mode"),
        "first_contact": say("Primo contatto", "First contact"),
        "daily_cap": say("Tetto giornaliero", "Daily cap"),
        "cooldown_hours": say("Attesa per mittente", "Wait per sender"),
        "expiry_days": say("Durata", "Lasts"),
    }


def _list_labels(kind: Any) -> Dict[str, str]:
    """List fields, in display order."""
    return {
        "cc": "Cc",
        "attachments": say("Allegati fissi", "Fixed attachments"),
        "trigger_values": say("Cartella", "Folder") if kind == "folder"
        else say("Mittenti", "Senders"),
        "doc_paths": say("Documenti", "Documents"),
    }


def describe(rule_like: Dict[str, Any], account_label: str = "") -> str:
    """The rule, in the user's language: fixed-size `Label: value` lines, then
    the lists (one prefixed item per line), then the instruction as a quoted
    block. A field absent from rule_like is left out."""
    r = rule_like
    lines = _account_line(account_label, r)
    for key, label in _scalar_labels().items():
        if key == "trigger_kind" or key not in r:
            continue
        shown = _mode_text(r[key]) if key in ("mode", "first_contact") else _scalar(key, r[key])
        lines.append(f"{label}: {shown}")
    for key, label in _list_labels(r.get("trigger_kind")).items():
        if key in r:
            lines.extend(_items(label, r[key]))
    if "reply_style" in r:
        lines.extend(_block(say("Istruzione", "Instruction"), r["reply_style"]))
    return "\n".join(lines)


def _same(a: Any, b: Any) -> bool:
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return list(a) == list(b)
    return a == b


def _update_body(rule_like: Dict[str, Any], before: Dict[str, Any],
                 account_label: str) -> str:
    lines: List[str] = []
    goes_auto = any(rule_like.get(k) == "auto" and before.get(k) != "auto"
                    for k in ("mode", "first_contact"))
    if goes_auto:
        lines.append(say(
            "⚠ La regola diventa AUTOMATICA: risponderà da sola, senza chiederti.",
            "⚠ The rule becomes AUTOMATIC: it will reply on its own, without asking you."))
    lines.extend(_account_line(account_label, before, rule_like))
    # Which rule: the console never shows rule ids, so the rule is named by
    # its current mode and trigger when the request does not change them.
    if "mode" in before and _same(rule_like.get("mode", before["mode"]), before["mode"]):
        lines.append(f"{_scalar_labels()['mode']}: {_mode_text(before['mode'])}")
    for key, label in _scalar_labels().items():
        if key in rule_like and not _same(rule_like[key], before.get(key)):
            lines.append(f"{label}: {_scalar(key, before.get(key))} → "
                         f"{_scalar(key, rule_like[key])}")
    kind = rule_like.get("trigger_kind", before.get("trigger_kind"))
    trigger_changes = any(k in rule_like and _as_list(rule_like[k]) != _as_list(before.get(k))
                          for k in ("trigger_kind", "trigger_values"))
    for key, label in _list_labels(kind).items():
        if key in rule_like and _as_list(rule_like[key]) != _as_list(before.get(key)):
            lines.extend(_items(say(f"{label}, prima", f"{label}, before"), before.get(key)))
            lines.extend(_items(say(f"{label}, dopo", f"{label}, after"), rule_like[key]))
    if "reply_style" in rule_like and not _same(rule_like["reply_style"],
                                                before.get("reply_style")):
        lines.extend(_block(say("Istruzione, prima", "Instruction, before"),
                            before.get("reply_style")))
        lines.extend(_block(say("Istruzione, dopo", "Instruction, after"),
                            rule_like["reply_style"]))
    # Last, what does not change: the change is read first, and a long list
    # of senders cannot push it out of a text cut short.
    if not trigger_changes and "trigger_values" in before:
        lines.extend(_items(_list_labels(kind)["trigger_values"], before["trigger_values"]))
    return "\n".join(lines)


def _target(rule_like: Dict[str, Any]) -> str:
    """The first trigger value, and how many more: "a@example.com (+2)"."""
    values = _as_list(rule_like.get("trigger_values"))
    target = values[0] if values else ""
    if len(values) > 1:
        target += f" (+{len(values) - 1})"
    return target


def _title(action: str, rule_like: Dict[str, Any], rule_id: Any,
           before: Optional[Dict[str, Any]] = None) -> str:
    """The first line every channel shows, a toast that shows nothing else
    included: what happens, to which rule, and AUTO when it sends by itself."""
    rid = _one(rule_id)
    mode = "AUTO" if rule_like.get("mode") == "auto" else "SEMI"
    if action == "create":
        target = _target(rule_like)
        if mode == "SEMI" and rule_like.get("first_contact") == "auto":
            return say(f"Nuova regola SEMI (primo contatto AUTO) per {target}",
                        f"New SEMI rule (first contact AUTO) for {target}")
        return say(f"Nuova regola {mode} per {target}", f"New {mode} rule for {target}")
    if action == "update":
        target = _target(before or {})
        if target:
            return say(f"Modifica regola per {target} ({rid})",
                        f"Change rule for {target} ({rid})")
        return say(f"Modifica regola {rid}", f"Change rule {rid}")
    target = _target(rule_like)
    whom_it = f" per {target} ({rid})" if target else f" {rid}"
    whom_en = f" for {target} ({rid})" if target else f" {rid}"
    # "regola SEMI (primo contatto AUTO)" / "SEMI rule (first contact AUTO)",
    # as the create title says it
    first_auto = mode == "SEMI" and rule_like.get("first_contact") == "auto"
    rule_it = f"regola {mode}" + (" (primo contatto AUTO)" if first_auto else "")
    rule_en = f"{mode} rule" + (" (first contact AUTO)" if first_auto else "")
    if action == "resume":
        return say(f"Riattiva {rule_it}{whom_it}", f"Resume {rule_en}{whom_en}")
    if action == "renew":
        try:
            days = float(rule_like.get("expiry_days"))
        except (TypeError, ValueError):
            days = 0.0
        if not days > 0:
            raise ValueError("rule has no duration")
        n = max(1, round(days))
        if target:
            return say(f"Rinnova {rule_it} per {target} per {n} giorni ({rid})",
                        f"Renew {rule_en} for {target} for {n} days ({rid})")
        return say(f"Rinnova {rule_it} {rid} per {n} giorni",
                    f"Renew {rule_en} {rid} for {n} days")
    return say(f"Elimina {rule_it}{whom_it}", f"Delete {rule_en}{whom_en}")


def preview(action: str, rule_like: Dict[str, Any], *,
            before: Optional[Dict[str, Any]] = None, account_label: str = "") -> Dict[str, Any]:
    """The approval preview of a rule request: `subject` (title) and `body`
    (text) are the keys every approval channel already reads."""
    if action not in ACTIONS:
        raise ValueError(f"unknown rule action: {action}")
    rule_id = rule_like.get("rule_id") or (before or {}).get("rule_id")
    if action == "update":
        body = _update_body(rule_like, before or {}, account_label)
    else:
        body = describe(rule_like, account_label)
    return {"action": "rule_" + action,
            "subject": _title(action, rule_like, rule_id, before),
            "body": body, "rule_id": rule_id}
