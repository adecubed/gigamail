"""DPAPI Windows via ctypes — nessuna dipendenza esterna.

Protegge byte legandoli all'utente Windows corrente: un file protetto
copiato su un'altra macchina (o letto da un altro utente) non è
decifrabile. Su piattaforme non-Windows available() è False e il
chiamante usa il proprio fallback.
"""
import ctypes
import ctypes.wintypes
import sys

_ENTROPY = b"gigamail-accounts-v1"


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", ctypes.wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_char)),
    ]


def available() -> bool:
    return sys.platform == "win32"


def _blob(data: bytes) -> "_DATA_BLOB":
    buf = ctypes.create_string_buffer(data, len(data))
    return _DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))


def _from_blob(blob: "_DATA_BLOB") -> bytes:
    try:
        return ctypes.string_at(blob.pbData, blob.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob.pbData)


def protect(data: bytes) -> bytes:
    if not available():
        raise OSError("DPAPI disponibile solo su Windows")
    inp = _blob(data)
    entropy = _blob(_ENTROPY)
    out = _DATA_BLOB()
    ok = ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(inp), None, ctypes.byref(entropy), None, None, 0, ctypes.byref(out)
    )
    if not ok:
        raise OSError("CryptProtectData fallita")
    return _from_blob(out)


def unprotect(data: bytes) -> bytes:
    if not available():
        raise OSError("DPAPI disponibile solo su Windows")
    inp = _blob(data)
    entropy = _blob(_ENTROPY)
    out = _DATA_BLOB()
    ok = ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(inp), None, ctypes.byref(entropy), None, None, 0, ctypes.byref(out)
    )
    if not ok:
        raise OSError("CryptUnprotectData fallita (utente/macchina diversi?)")
    return _from_blob(out)
