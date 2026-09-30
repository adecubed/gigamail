# GigaMail — mail for your AI agent
# Copyright (C) 2026 Adecubed
# Licensed under the GNU AGPL v3 or later. See LICENSE.
"""PIN per approvare da un canale che non ha Windows Hello.

Serve a un caso preciso: su Telegram un tap approva, quindi chiunque
abbia il telefono sbloccato puo' far partire una mail. Il PIN aggiunge la
seconda meta' — non basta avere il dispositivo, bisogna anche sapere
qualcosa.

Non e' Hello e non pretende di esserlo. Il PIN attraversa Telegram in
chiaro: sta nella cronologia della chat e sui server di Telegram finche'
il messaggio non viene cancellato. E' una barriera contro il telefono
lasciato sbloccato sul tavolo, non contro chi controlla l'account
Telegram. Per questo l'approvazione forte resta quella dal PC.

Conservato solo come hash: scrypt con sale casuale. Un PIN e' corto e
quindi forzabile per tentativi — il costo di scrypt e il blocco dopo
pochi errori (gestito dal chiamante) sono cio' che lo rende praticabile.
"""
import hashlib
import hmac
import secrets
from typing import Optional, Tuple

# scrypt: n alto perche' lo spazio dei PIN e' minuscolo e l'unica difesa
# vera e' rendere caro ogni tentativo.
_N = 1 << 15
_R = 8
_P = 1
_DKLEN = 32
# OpenSSL rifiuta scrypt oltre 32 MB se non glielo si dice: con n=2^15
# servono ~32 MB e il default lo taglia fuori. Si alza il tetto invece
# di abbassare n, perche' n e' esattamente la parte che protegge un
# segreto corto.
_MAXMEM = 64 * 1024 * 1024

PIN_MIN = 4
PIN_MAX = 12


def valid_pin(pin: str) -> Tuple[bool, str]:
    """Un PIN accettabile. Il messaggio spiega il perche', perche' viene
    mostrato all'umano che lo sta scegliendo."""
    pin = (pin or "").strip()
    if not pin.isdigit():
        return False, "Il PIN deve essere composto solo da cifre."
    if not (PIN_MIN <= len(pin) <= PIN_MAX):
        return False, f"Il PIN deve avere da {PIN_MIN} a {PIN_MAX} cifre."
    if len(set(pin)) == 1:
        return False, "Un PIN di cifre tutte uguali non protegge nulla."
    if pin in ("1234", "0000", "1111", "123456", "12345", "4321"):
        return False, "PIN troppo comune: scegline un altro."
    return True, ""


def hash_pin(pin: str) -> str:
    """'scrypt$<sale>$<hash>', da mettere nello store. Mai il PIN."""
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(pin.encode("utf-8"), salt=salt, n=_N, r=_R, p=_P,
                        dklen=_DKLEN, maxmem=_MAXMEM)
    return f"scrypt${salt.hex()}${dk.hex()}"


def verify_pin(pin: str, stored: Optional[str]) -> bool:
    """Confronto a tempo costante. `stored` vuoto = nessun PIN impostato:
    torna False, cosi' un record mancante non diventa un lasciapassare."""
    if not stored or not pin:
        return False
    try:
        algo, salt_hex, hash_hex = stored.split("$", 2)
        if algo != "scrypt":
            return False
        dk = hashlib.scrypt(pin.encode("utf-8"), salt=bytes.fromhex(salt_hex),
                            n=_N, r=_R, p=_P, dklen=_DKLEN,
                            maxmem=_MAXMEM)
    except Exception:
        return False
    return hmac.compare_digest(dk.hex(), hash_hex)


def looks_like_pin(text: str) -> bool:
    """Un messaggio che sembra un PIN: sole cifre, lunghezza plausibile.
    Serve a non scambiare per PIN una frase qualsiasi scritta in chat."""
    t = (text or "").strip()
    return t.isdigit() and PIN_MIN <= len(t) <= PIN_MAX
