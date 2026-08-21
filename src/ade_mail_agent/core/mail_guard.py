# GigaMail — mail for your AI agent
# Copyright (C) 2026 Adecubed
# Licensed under the GNU AGPL v3 or later. See LICENSE.
"""Barriere anti-spam davanti alle regole di risposta (0.2).

Tutte deterministiche e locali: nessun LLM decide se rispondere. Il LLM
scrive il testo SOLO dopo che queste barriere hanno detto si'. Ordine:

  1. DMARC (Authentication-Results): senza un From autenticato la whitelist
     non vale nulla — chiunque puo' scrivere "From: cliente@fidato.it".
     fail/assente → MAI auto: al massimo semi (l'umano vede e decide).
  2. RFC 3834: mai rispondere a posta automatica (Auto-Submitted,
     Precedence bulk/junk/list, List-Id/List-Unsubscribe,
     X-Auto-Response-Suppress, Return-Path vuoto, no-reply@).
  3. Verdetto del provider: X-Spam-Flag rispettato; le cartelle spam non
     vengono nemmeno lette dal watcher. Non scavalchiamo mai il filtro.
  7. Allegati eseguibili/archivi e messaggi abnormi: nessun trigger.

(4 anti-loop sta nel percorso di invio: le nostre auto-risposte escono
marcate. 5 cooldown e 6 raffica hanno bisogno di memoria e vivono nel
watcher, su rules.handled.)

Interfaccia: check(headers, message) → Verdict. Le intestazioni arrivano
come dict {nome-minuscolo: [valori]} da mail_router.get_message_headers.
Fail-closed: header non leggibili = mail non trattabile in auto.
"""
from typing import Any, Dict, List, Optional

# Localpart che identificano caselle senza umano dietro.
_NOREPLY_LOCALPARTS = (
    "no-reply", "noreply", "do-not-reply", "donotreply", "do_not_reply",
    "mailer-daemon", "postmaster", "bounce", "bounces",
)

# Estensioni che non devono mai innescare una risposta automatica:
# eseguibili, script, archivi (possono contenere entrambi), immagini disco.
_BLOCKED_EXTENSIONS = (
    ".exe", ".bat", ".cmd", ".com", ".scr", ".pif", ".msi", ".dll",
    ".js", ".jse", ".vbs", ".vbe", ".wsf", ".ps1", ".hta", ".jar",
    ".zip", ".rar", ".7z", ".tar", ".gz", ".iso", ".img", ".lnk",
)

# Un corpo oltre questa soglia non e' una mail da rispondere in automatico.
MAX_BODY_CHARS = 200_000


class Verdict:
    """Esito delle barriere: reply=False non si risponde affatto;
    reply=True, auto_ok=False si puo' solo proporre (semi);
    reply=True, auto_ok=True la regola puo' anche andare in auto."""

    def __init__(self, reply: bool, auto_ok: bool, reasons: List[str]):
        self.reply = reply
        self.auto_ok = auto_ok and reply
        self.reasons = reasons

    def __repr__(self):
        return f"Verdict(reply={self.reply}, auto_ok={self.auto_ok}, reasons={self.reasons})"


def _get(headers: Dict[str, List[str]], name: str) -> List[str]:
    return [str(v) for v in (headers or {}).get(name.lower(), [])]


def _first(headers: Dict[str, List[str]], name: str) -> str:
    vals = _get(headers, name)
    return vals[0].strip() if vals else ""


def sender_address(message: Dict[str, Any]) -> str:
    """Indirizzo del From dal messaggio normalizzato (Graph o IMAP)."""
    f = message.get("from") or message.get("sender") or ""
    if isinstance(f, dict):
        return (f.get("emailAddress", {}).get("address")
                or f.get("address") or "").strip().lower()
    s = str(f)
    if "<" in s and ">" in s:
        s = s[s.rfind("<") + 1:s.rfind(">")]
    return s.strip().lower()


def dmarc_pass(headers: Dict[str, List[str]]) -> bool:
    """True SOLO se una Authentication-Results dichiara dmarc=pass.
    L'header lo scrive il NOSTRO server di posta (l'ultimo hop): un
    mittente puo' falsificarne uno suo, ma il provider antepone il proprio.
    Qui guardiamo se esiste un verdetto pass; assente = non autenticato."""
    for ar in _get(headers, "authentication-results"):
        low = ar.lower()
        if "dmarc=pass" in low:
            return True
    return False


def is_auto_generated(headers: Dict[str, List[str]], message: Dict[str, Any]) -> Optional[str]:
    """RFC 3834 e dintorni: la ragione per cui NON si risponde, o None."""
    auto_submitted = _first(headers, "auto-submitted").lower()
    if auto_submitted and auto_submitted != "no":
        return f"auto-submitted:{auto_submitted.split(';')[0]}"
    precedence = _first(headers, "precedence").lower()
    if precedence in ("bulk", "junk", "list", "auto_reply"):
        return f"precedence:{precedence}"
    if _get(headers, "list-id") or _get(headers, "list-unsubscribe"):
        return "mailing-list"
    if _get(headers, "x-auto-response-suppress"):
        return "x-auto-response-suppress"
    if "return-path" in (headers or {}):
        rp = _first(headers, "return-path").strip()
        if rp in ("", "<>"):
            return "empty-return-path"
    sender = sender_address(message)
    local = sender.split("@", 1)[0] if "@" in sender else sender
    for marker in _NOREPLY_LOCALPARTS:
        if local == marker or local.startswith(marker + "+") or local.startswith(marker + "."):
            return f"noreply-sender:{local}"
    return None


def provider_says_spam(headers: Dict[str, List[str]]) -> bool:
    if _first(headers, "x-spam-flag").lower().startswith("yes"):
        return True
    if _first(headers, "x-spam-status").lower().startswith("yes"):
        return True
    return False


def has_blocked_attachment(message: Dict[str, Any]) -> Optional[str]:
    for att in message.get("attachments") or []:
        name = str((att or {}).get("name") or "").lower()
        for ext in _BLOCKED_EXTENSIONS:
            if name.endswith(ext):
                return name
    return None


def body_too_large(message: Dict[str, Any]) -> bool:
    body = message.get("body")
    if isinstance(body, dict):
        body = body.get("content") or ""
    return len(str(body or "")) > MAX_BODY_CHARS


def check(headers: Optional[Dict[str, List[str]]],
          message: Dict[str, Any]) -> Verdict:
    """Applica le barriere. `headers=None` = header non recuperabili:
    fail-closed, la mail al massimo si propone all'umano (semi), e solo se
    il resto del messaggio e' pulito."""
    reasons: List[str] = []

    auto_reason = is_auto_generated(headers or {}, message)
    if auto_reason:
        return Verdict(False, False, [auto_reason])
    if headers is not None and provider_says_spam(headers):
        return Verdict(False, False, ["provider-spam-verdict"])
    blocked = has_blocked_attachment(message)
    if blocked:
        return Verdict(False, False, [f"blocked-attachment:{blocked}"])
    if body_too_large(message):
        return Verdict(False, False, ["body-too-large"])

    if headers is None:
        reasons.append("headers-unavailable")
        return Verdict(True, False, reasons)
    if not dmarc_pass(headers):
        reasons.append("dmarc-not-pass")
        return Verdict(True, False, reasons)
    return Verdict(True, True, reasons)
