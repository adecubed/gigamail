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
  Altri    (Linux) PIN locale, digitato in un terminale interattivo.

Il PIN locale e' PIU' DEBOLE di Hello e lo dichiariamo: un processo che
gira come l'utente puo' leggere lo store o simulare un terminale. Chiude
pero' il caso normale, l'agente che lancia `gigamail approvals approve`
da uno script: senza terminale il prompt non si apre, e senza il PIN non
passa. Hash scrypt, blocco dopo 3 errori. Si imposta con
`gigamail approvals pin`; senza PIN impostato non c'e' backend.

Regola: se nessun backend puo' chiedere a un umano, require_human() dice
NO. Mai fail-open. Il chiamante (CLI, console) deve rifiutare l'azione,
non degradare a un "sei sicuro? [s/N]".

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


# What UserConsentVerifier.check_availability_async answers, and what to
# do about it. Before, every answer but "available" collapsed into "no
# backend": on a PC where the console never showed the prompt, nothing
# said whether the WinRT package was missing, Hello was not set up for
# that Windows account, or group policy had switched it off.
_DISPONIBILITA_WIN = {
    0: "",
    1: "nessun dispositivo Hello su questo PC (DeviceNotPresent)",
    2: "Windows Hello non e' configurato per questo utente Windows "
       "(NotConfiguredForUser): Impostazioni > Account > Opzioni di "
       "accesso, imposta un PIN",
    3: "Windows Hello e' disabilitato da criteri di gruppo "
       "(DisabledByPolicy)",
    4: "Windows Hello e' occupato da un'altra verifica (DeviceBusy)",
}

_motivo_indisponibile = ""


def unavailable_reason() -> str:
    """Why the last backend check found nothing to ask the human with.
    Empty when a backend is available or no check has run yet."""
    return _motivo_indisponibile


def _win_available() -> bool:
    global _motivo_indisponibile
    try:
        from winrt.windows.security.credentials.ui import (  # type: ignore
            UserConsentVerifier,
        )
        from winrt.windows.security.credentials.ui import (
            UserConsentVerifierAvailability as A,
        )
    except ImportError as e:
        _motivo_indisponibile = (
            "il pacchetto Python winrt-Windows.Security.Credentials.UI non "
            f"e' importabile in questo Python ({sys.executable}): {e}")
        return False
    try:
        r = _run_winrt(UserConsentVerifier.check_availability_async())
    except Exception as e:
        _motivo_indisponibile = f"check_availability_async fallita: {e}"
        return False
    if int(r) == int(A.AVAILABLE):
        _motivo_indisponibile = ""
        return True
    _motivo_indisponibile = _DISPONIBILITA_WIN.get(
        int(r), f"disponibilita' {int(r)} non riconosciuta")
    return False


# Perche' Windows ha detto di no. Tutti restano un NO — la sicurezza
# non cambia — ma "hai annullato" e "su questo PC Hello non e'
# configurato" richiedono due azioni diverse, e appiattirli sulla
# stessa frase lascia l'utente a indovinare quale dei due sia.
_MOTIVI_WIN = {
    0: "verificato",
    1: "su questo PC non e' configurato nessun metodo Hello (PIN, "
       "impronta o volto)",
    2: "Windows Hello non e' disponibile su questo dispositivo",
    3: "dispositivo occupato: un'altra verifica e' gia' in corso",
    4: "tentativi esauriti",
    5: "annullata",
}

_ultimo_motivo = ""


def last_reason() -> str:
    """Perche' l'ultima richiesta di conferma e' stata respinta.
    Vuoto se l'ultima e' andata a buon fine o non ce n'e' stata."""
    return _ultimo_motivo


def _win_ask(reason: str) -> bool:
    global _ultimo_motivo
    from winrt.windows.security.credentials.ui import (
        UserConsentVerificationResult as R,
    )
    from winrt.windows.security.credentials.ui import (  # type: ignore
        UserConsentVerifier,
    )
    # Il messaggio e' mostrato dentro il dialogo di Windows Hello.
    r = _run_winrt(UserConsentVerifier.request_verification_async(reason))
    ok = int(r) == int(R.VERIFIED)
    _ultimo_motivo = "" if ok else _MOTIVI_WIN.get(
        int(r), f"esito {int(r)} non riconosciuto")
    return ok


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


# ------------------------------------------------- PIN locale (Linux & co.)

_PIN_KV = "local_approve_pin"
_PIN_FAILS = "local_pin_fails"
_PIN_LOCKED = "local_pin_locked_until"
PIN_MAX_FAILS = 3
PIN_LOCK_SECONDS = 15 * 60


def _rules_store():
    from gigamail.core import rules as rules_mod
    return rules_mod.store()


def _terminale() -> bool:
    """Un umano davanti a un terminale vero. Un agente che lancia il
    comando da uno script ha stdin/stdout su pipe."""
    try:
        return sys.stdin.isatty() and sys.stdout.isatty()
    except Exception:
        return False


def local_pin_set() -> bool:
    try:
        return bool(_rules_store().kv_get(_PIN_KV, ""))
    except Exception:
        return False


def local_pin_locked() -> int:
    """Secondi di blocco rimanenti dopo troppi PIN sbagliati, 0 se libero."""
    import time
    fino = float(_rules_store().kv_get(_PIN_LOCKED, "0") or 0)
    resta = int(fino - time.time())
    return resta if resta > 0 else 0


def verify_local_pin(pin: str) -> bool:
    """Controlla il PIN e tiene il conto degli errori (blocco dopo 3)."""
    import time

    from gigamail.core import approval_pin
    rs = _rules_store()
    if local_pin_locked():
        return False
    if approval_pin.verify_pin(pin, rs.kv_get(_PIN_KV, "")):
        rs.kv_set(_PIN_FAILS, "0")
        return True
    falliti = int(rs.kv_get(_PIN_FAILS, "0") or 0) + 1
    if falliti >= PIN_MAX_FAILS:
        rs.kv_set(_PIN_FAILS, "0")
        rs.kv_set(_PIN_LOCKED, str(time.time() + PIN_LOCK_SECONDS))
    else:
        rs.kv_set(_PIN_FAILS, str(falliti))
    return False


def set_local_pin(pin_hash: str) -> None:
    rs = _rules_store()
    rs.kv_set(_PIN_KV, pin_hash)
    rs.kv_set(_PIN_FAILS, "0")
    rs.kv_set(_PIN_LOCKED, "0")


def _pin_available() -> bool:
    return not _WIN and not _MAC and local_pin_set() and _terminale()


def _pin_ask(reason: str) -> bool:
    global _ultimo_motivo
    import getpass
    bloccato = local_pin_locked()
    if bloccato:
        _ultimo_motivo = f"PIN bloccato per altri {bloccato}s dopo troppi errori"
        return False
    print(f"\n{reason}")
    pin = getpass.getpass("PIN di approvazione (non viene mostrato): ").strip()
    ok = verify_local_pin(pin)
    if not ok:
        _ultimo_motivo = ("PIN errato" if not local_pin_locked() else
                          f"PIN errato: bloccato per {PIN_LOCK_SECONDS // 60} minuti")
    return ok


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
    if _pin_available():
        return "terminal-pin"
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
    global _ultimo_motivo
    _ultimo_motivo = ""
    override = _test_override()
    if override is not None:
        return override(reason)
    if _WIN and _win_available():
        return _win_ask(reason)
    if _MAC and _mac_available():
        return _mac_ask(reason)
    if _pin_available():
        return _pin_ask(reason)
    if not _WIN and not _MAC:
        raise ConsentUnavailable(
            "nessun Windows Hello o Touch ID su questa macchina. Imposta un "
            "PIN locale con `gigamail approvals pin`, poi approva da un "
            "terminale interattivo (non da uno script)."
            if not local_pin_set() else
            "il PIN locale si digita in un terminale interattivo: questo "
            "comando non ne ha uno (lanciato da uno script o da un agente?)."
        )
    raise ConsentUnavailable(
        "Nessun modo di chiedere conferma all'utente su questa macchina "
        "(serve Windows Hello o macOS LocalAuthentication)"
        + (f": {_motivo_indisponibile}" if _motivo_indisponibile else "")
        + ". Verifica con `gigamail approvals check`."
    )


def check() -> dict:
    """What a human would be asked with here, and why not: for
    `gigamail approvals check` and the console's status card."""
    name = backend_name()
    return {"backend": name, "reason": "" if name else unavailable_reason(),
            "python": sys.executable, "platform": sys.platform}
