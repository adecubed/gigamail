# GigaMail — mail for your AI agent
# Copyright (C) 2026 Adecubed
# Licensed under the GNU AGPL v3 or later. See LICENSE.
"""Consenso umano che un processo non puo' fornire.

Perche' esiste (r/mcp, agosto 2026)
-----------------------------------
L'approvazione fuori banda (console o CLI) basta contro un'istruzione
iniettata in una mail, ma non contro l'agente che il gate dovrebbe
supervisionare, se quell'agente ha una shell: `gigamail approvals approve
<id>` e' a una chiamata di tool dal gate. "Fuori banda rispetto a MCP" non
e' "fuori banda rispetto all'agente" finche' approvare e' un comando.

Questo modulo rende l'approvazione qualcosa che un processo puo' INVOCARE
ma non SODDISFARE: un prompt dell'OS sulla sessione fisica dell'utente.
Il processo lo apre e resta in attesa; solo l'umano lo chiude. Niente
codice da digitare, niente file da leggere, niente schermo da catturare.

Backend
-------
  Windows  UserConsentVerifier (Windows Hello: PIN/impronta/volto), WinRT.
           Misurato dal vivo il 2026-08-19 su Windows 11: il prompt scatta
           A OGNI chiamata, nessuna cache stile sudo (seconda richiesta
           immediata dopo una VERIFIED → nuovo prompt, 24 s di attesa
           umana). Si apre anche da un processo senza finestra.
  macOS    LocalAuthentication (Touch ID / password), reuse duration 0.
  Linux    nessun backend affidabile senza desktop → NON disponibile.

Regola: se nessun backend puo' chiedere a un umano, require_human() dice
NO. Mai fail-open. Il chiamante (CLI, console) deve rifiutare l'azione e
indicare la console, non degradare a una conferma da tastiera.

Test (ADE_MAIL_DRYRUN / suite): GIGAMAIL_CONSENT_BACKEND=deny|allow forza
l'esito senza UI. `allow` e' ammesso SOLO se ADE_MAIL_DRYRUN e' attivo:
fuori dal dry-run la variabile viene ignorata e vale il backend reale.
"""
import os
import sys
from typing import Callable, Optional

_WIN = sys.platform == "win32"
_MAC = sys.platform == "darwin"


class ConsentUnavailable(RuntimeError):
    """Nessun backend in grado di chiedere a un umano su questa macchina."""


# ------------------------------------------------------------------ Windows

def _run_winrt(op):
    """Attende un IAsyncOperation WinRT da codice sincrono.
    asyncio.run vuole una coroutine (su 3.10 rifiuta l'operazione nuda):
    la avvolgiamo. Funziona anche se un event loop e' gia' attivo nel
    thread (console FastAPI): in quel caso usiamo un thread dedicato."""
    import asyncio
    import threading

    async def _await():
        return await op

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_await())
    box = {}

    def _runner():
        box["r"] = asyncio.run(_await())

    t = threading.Thread(target=_runner, daemon=True)
    t.start()
    t.join()
    return box.get("r")


def _win_available() -> bool:
    try:
        from winrt.windows.security.credentials.ui import (  # type: ignore
            UserConsentVerifier, UserConsentVerifierAvailability as A,
        )
    except ImportError:
        return False
    try:
        r = _run_winrt(UserConsentVerifier.check_availability_async())
        return int(r) == int(A.AVAILABLE)
    except Exception:
        return False


def _win_ask(reason: str) -> bool:
    from winrt.windows.security.credentials.ui import (  # type: ignore
        UserConsentVerifier, UserConsentVerificationResult as R,
    )
    # Il messaggio e' mostrato dentro il dialogo di Windows Hello.
    r = _run_winrt(UserConsentVerifier.request_verification_async(reason))
    # Tutto cio' che non e' VERIFIED (CANCELED, DEVICE_BUSY,
    # RETRIES_EXHAUSTED, NOT_CONFIGURED_FOR_USER, ...) e' un NO.
    return int(r) == int(R.VERIFIED)


# -------------------------------------------------------------------- macOS

def _mac_available() -> bool:
    try:
        import LocalAuthentication  # type: ignore  # pyobjc-framework-LocalAuthentication
    except ImportError:
        return False
    ctx = LocalAuthentication.LAContext.alloc().init()
    ok, _err = ctx.canEvaluatePolicy_error_(
        LocalAuthentication.LAPolicyDeviceOwnerAuthentication, None)
    return bool(ok)


def _mac_ask(reason: str) -> bool:
    import threading
    import LocalAuthentication  # type: ignore
    ctx = LocalAuthentication.LAContext.alloc().init()
    # Nessun riuso della verifica precedente: ogni approvazione e' una
    # verifica. (Default 0, ma lo fissiamo: e' la proprieta' che conta.)
    ctx.setTouchIDAuthenticationAllowableReuseDuration_(0)
    done = threading.Event()
    result = {"ok": False}

    def _reply(success, error):
        result["ok"] = bool(success)
        done.set()

    ctx.evaluatePolicy_localizedReason_reply_(
        LocalAuthentication.LAPolicyDeviceOwnerAuthentication, reason, _reply)
    done.wait()
    return result["ok"]


# ----------------------------------------------------------------- registry

def _test_override() -> Optional[Callable[[str], bool]]:
    """Override per test/harness. 'allow' solo in dry-run, mai altrimenti."""
    mode = os.environ.get("GIGAMAIL_CONSENT_BACKEND", "").strip().lower()
    if not mode:
        return None
    dry = os.environ.get("ADE_MAIL_DRYRUN", "") not in ("", "0", "false")
    if mode == "deny":
        return lambda _r: False
    if mode == "allow" and dry:
        return lambda _r: True
    return None  # 'allow' fuori dal dry-run: ignorato, vale il backend reale


def backend_name() -> Optional[str]:
    """Nome del backend che verrebbe usato, o None se nessuno e' disponibile."""
    if _test_override() is not None:
        return "test-override"
    if _WIN and _win_available():
        return "windows-hello"
    if _MAC and _mac_available():
        return "macos-local-authentication"
    return None


def available() -> bool:
    return backend_name() is not None


def require_human(reason: str) -> bool:
    """Chiede all'utente fisico della macchina di confermare `reason`.

    Ritorna True SOLO se l'umano ha verificato la propria identita' in
    questo istante, per questa richiesta. Ritorna False se ha annullato,
    se la verifica e' fallita, o per qualunque altro esito.
    Solleva ConsentUnavailable se nessun backend puo' chiedere: il
    chiamante deve trattarlo come un NO e indicare la console.
    """
    override = _test_override()
    if override is not None:
        return override(reason)
    if _WIN and _win_available():
        return _win_ask(reason)
    if _MAC and _mac_available():
        return _mac_ask(reason)
    raise ConsentUnavailable(
        "Nessun modo di chiedere conferma all'utente su questa macchina "
        "(serve Windows Hello o macOS LocalAuthentication). Approva dalla "
        "console GigaMail."
    )
