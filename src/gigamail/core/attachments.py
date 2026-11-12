# GigaMail — mail for your AI agent
# Copyright (C) 2026 Adecubed
# Licensed under the GNU AGPL v3 or later. See LICENSE.
"""Allegati: dai nomi ai file, solo dentro l'identity dell'account.

Vive qui e non nel server MCP perche' lo usano due percorsi di invio
diversi — i tool (send_mail, reply_mail) e le regole del watcher — e una
seconda copia della stessa logica finirebbe per divergere: e' la deriva
silenziosa che gia' e' costata una planimetria sbagliata a un cliente.
"""
import base64
import binascii
import hashlib
import hmac
import mimetypes
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from gigamail.core import accounts as core_accounts
from gigamail.core import identity_reader

# Le frasi con cui una mail promette un allegato. Servono a non spedire
# "in allegato trova le planimetrie" con zero file: e' successo il 19 e
# il 23 settembre, e il cliente riceve una mail che si contraddice.
_PROMESSA = re.compile(
    r"in allegato|in allegati|negli allegati|allegat[aeio]\b|allego\b",
    re.IGNORECASE)


class AttachmentChanged(ValueError):
    """Il file da spedire non e' piu' quello approvato.

    ValueError perche' il percorso di esecuzione tratta gia' cosi' una
    richiesta non eseguibile: la mail non parte e l'errore arriva a chi
    ha chiamato."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def codici_citati(testo: str) -> List[str]:
    """I codici di documento nominati nel testo, in ordine e senza
    ripetizioni, secondo le estensioni accese.

    Serve a far seguire gli allegati al CONTENUTO della mail: una lista
    fissa nella regola spedirebbe sempre gli stessi file, qualunque cosa
    chieda il cliente. Il core non sa che forma abbia un codice (A.9.2 per
    un'agenzia, SKU-12 per un negozio): lo dice l'estensione. Senza
    estensioni non si legge niente e resta la lista della regola."""
    from gigamail.core import extensions
    visti: List[str] = []
    for ext in extensions.active():
        for c in ext.cited_codes(testo) or []:
            if c not in visti:
                visti.append(c)
    return visti


def promette_allegati(testo: str) -> bool:
    """Il testo annuncia un allegato."""
    return bool(_PROMESSA.search(str(testo or "")))


def identity_paths(account_id: Optional[int]) -> List[str]:
    aid = account_id or (core_accounts.get_active_account() or {}).get("id")
    if not aid:
        return []
    return core_accounts.get_identity(aid).get("file_paths") or []


def resolve(account_id: Optional[int],
            names: Optional[List[str]]) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Nomi -> file REGISTRATI nell'identity, con il percorso.

    Il vincolo e' il punto: si allega solo cio' che l'utente ha registrato
    per quell'account, mai un percorso arbitrario. Senza, l'invio
    diventerebbe il modo piu' comodo per far uscire dal disco un file
    qualunque, e l'approvazione umana non basterebbe: l'umano approva un
    nome, non sceglie il file.

    Pretende una corrispondenza UNIVOCA. 'A.7.4' deve dare A.7.4.pdf, mai
    il primo di una rosa di simili: allegare la planimetria sbagliata non
    produce nessun errore — la mail parte, sembra giusta, e dentro c'e'
    un altro appartamento.

    Fissa anche il CONTENUTO: sha256 e dimensione dei byte letti adesso.
    Il percorso da solo non basta: fra l'approvazione e l'invio il file
    su disco si puo' sostituire (Loopjacking), e l'umano avrebbe
    approvato un nome mentre parte un altro contenuto. L'hash entra negli
    argomenti della richiesta, quindi e' parte di cio' che viene
    approvato, e payload() lo ricontrolla all'invio.

    Ritorna (risolti, mancanti); i mancanti fermano il chiamante.
    """
    if not names:
        return [], []
    paths = identity_paths(account_id)
    risolti: List[Dict[str, Any]] = []
    mancanti: List[str] = []
    for n in names:
        n = str(n)
        match = identity_reader.find_files_by_names(paths, [n])
        radice = n.rsplit(".", 1)[0] if n.lower().endswith(
            tuple(identity_reader._ESTENSIONI)) else n
        esatti = [f for f in match
                  if f["name_no_ext"].lower() == radice.lower()]
        scelti = esatti or match
        if len(scelti) == 1:
            f = scelti[0]
            try:
                with open(f["path"], "rb") as fh:
                    data = fh.read()
            except OSError:
                mancanti.append(f"{n} (illeggibile)")
                continue
            risolti.append({"name": f["name"], "path": f["path"],
                            "sha256": _sha256(data), "size": len(data)})
        elif not scelti:
            mancanti.append(n)
        else:
            mancanti.append(
                f"{n} (ambiguo: " + ", ".join(f["name"] for f in scelti[:5]) + ")")
    return risolti, mancanti


def preview(risolti: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """Cosa l'umano vede prima di approvare: nome, percorso, peso e
    impronta del contenuto di ogni file che uscira'. Peso e impronta sono
    quelli fissati da resolve(), non riletti dal disco: l'anteprima
    descrive esattamente i byte che payload() accettera' di spedire."""
    out = []
    for f in risolti or []:
        size = f.get("size")
        sha = f.get("sha256")
        item = {"name": f["name"], "path": f["path"],
                "size_kb": round(size / 1024, 1) if size is not None else None,
                "sha256": sha[:12] if sha else None}
        if f.get("outside"):
            item["outside"] = True
        out.append(item)
    return out


def payload(risolti: Optional[List[Dict[str, Any]]]) -> List[Dict[str, str]]:
    """Legge i file al momento dell'INVIO e li porta nel formato di
    mail_router: [{name, data_b64, type}].

    Fail-closed: se i byte non hanno piu' l'hash fissato alla creazione
    della richiesta, o se la richiesta non ne ha uno (creata prima di
    questo controllo), non parte niente. Meglio una mail da rifare che
    un allegato diverso da quello approvato."""
    out = []
    for f in risolti or []:
        atteso = f.get("sha256")
        if not atteso:
            raise AttachmentChanged(
                f"Allegato {f.get('name')}: la richiesta non fissa il "
                "contenuto del file. Creane una nuova e falla approvare. "
                "Niente e' stato inviato.")
        with open(f["path"], "rb") as fh:
            data = fh.read()
        if not hmac.compare_digest(_sha256(data), str(atteso)):
            raise AttachmentChanged(
                f"Allegato {f.get('name')}: il file e' cambiato dopo "
                "l'approvazione. Creane una nuova richiesta e falla "
                "approvare. Niente e' stato inviato.")
        tipo = mimetypes.guess_type(f["name"])[0] or "application/octet-stream"
        out.append({"name": f["name"], "type": tipo,
                    "data_b64": base64.b64encode(data).decode("ascii")})
    return out


# ── Files a person adds to a draft ───────────────────────────────────
# resolve() binds the AGENT to the files registered in the identity: it
# names a file, it never picks one from the disk. A person correcting a
# draft in the approval window is the other case: they pick the file
# themselves, from anywhere on the disk or from another mail, and picking
# it is the decision. The bytes are copied next to the approvals store, so
# the request keeps one shape for every attachment (name, path, sha256,
# size) and payload() checks these like the others before sending.
MAX_ADDED_BYTES = 25 * 1024 * 1024
# A copy is kept this long after its request stopped waiting: the send
# that follows an approval reads it a moment after the request is consumed.
_STAGED_GRACE_SECONDS = 3600
_REQUEST_ID = re.compile(r"[A-Za-z0-9_-]{1,80}")


def _say(it: str, en: str) -> str:
    from gigamail import policy
    return it if policy.user_lang() == "it" else en


def staging_root() -> Path:
    from gigamail.core.data_paths import app_root
    return app_root() / "approval_attachments"


def stage(request_id: str, files: Optional[List[Dict[str, Any]]],
          existing: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """Copies the files a person added to a pending request ([{name,
    data_b64}]) and returns them resolved like resolve() does, marked
    added_by "person". `existing` are the attachments the request already
    has: the same file twice is taken once, another file under a name
    already there is refused, and so is anything past MAX_ADDED_BYTES in
    total. A program is never attached. Raises ValueError with a text for
    the user; nothing is written unless every file is accepted."""
    from gigamail.core import mail_guard
    if not _REQUEST_ID.fullmatch(str(request_id or "")):
        raise ValueError("not a request id")
    known = {str(f.get("name") or "").lower(): f.get("sha256") for f in existing or []}
    total = sum(int(f.get("size") or 0) for f in existing or [])
    accepted = []
    for f in files or []:
        f = f if isinstance(f, dict) else {}
        name = os.path.basename(str(f.get("name") or "").replace(chr(92), "/")).strip()
        if not name:
            raise ValueError(_say("Un allegato non ha nome.", "An attachment has no name."))
        if mail_guard.is_executable_name(name):
            raise ValueError(_say(f"{name}: è un programma, non si allega.",
                                  f"{name}: it is a program, it is not attached."))
        try:
            data = base64.b64decode(str(f.get("data_b64") or ""), validate=True)
        except (binascii.Error, ValueError):
            data = b""
        if not data:
            raise ValueError(_say(f"{name}: file vuoto o illeggibile.",
                                  f"{name}: empty or unreadable file."))
        sha = _sha256(data)
        if name.lower() in known:
            if known[name.lower()] == sha:
                continue
            raise ValueError(_say(f"{name}: c'è già un allegato diverso con questo nome.",
                                  f"{name}: another attachment already has this name."))
        total += len(data)
        if total > MAX_ADDED_BYTES:
            raise ValueError(_say("Allegati troppo grandi (massimo 25 MB in tutto).",
                                  "Attachments too large (25 MB at most in total)."))
        known[name.lower()] = sha
        accepted.append((name, data, sha))
    out = []
    folder = staging_root() / str(request_id)
    for name, data, sha in accepted:
        folder.mkdir(parents=True, exist_ok=True)
        # Stored under fingerprints of content and name: the name the
        # person gave is kept in the request, never used as a path.
        path = folder / f"{sha[:32]}-{_sha256(name.lower().encode('utf-8'))[:8]}"
        with open(path, "wb") as fh:
            fh.write(data)
        out.append({"name": name, "path": str(path), "sha256": sha,
                    "size": len(data), "added_by": "person"})
    return out


def discard(staged: Optional[List[Dict[str, Any]]]) -> None:
    """Removes copies just made for a request that then did not take them."""
    for f in staged or []:
        try:
            os.remove(f["path"])
        except (OSError, KeyError):
            pass


def discard_stale(still_waiting: Callable[[str], bool]) -> int:
    """Removes the copies of the requests that no longer wait (sent,
    rejected, expired), an hour after the last file was added. Returns how
    many requests were cleaned."""
    root = staging_root()
    if not root.is_dir():
        return 0
    removed = 0
    for folder in root.iterdir():
        try:
            if (not folder.is_dir() or still_waiting(folder.name)
                    or folder.stat().st_mtime > time.time() - _STAGED_GRACE_SECONDS):
                continue
        except OSError:
            continue
        shutil.rmtree(folder, ignore_errors=True)
        removed += 1
    return removed


# ── A file the agent asks for by its path ────────────────────────────
# The agent cannot browse the disk, and by name it reaches only the
# registered files. When the user tells it which file they mean ("attach
# C:/Documents/offer.pdf"), it may ask for that one file by its full
# path. The request is marked "outside": the approval shows the whole
# path, and it can be given only at the PC (policy.outside_files).
def is_path(name: Any) -> bool:
    return os.path.isabs(str(name or "").strip())


def _is_gigamail_data(real: str) -> bool:
    from gigamail.core.data_paths import app_root, data_root
    target = Path(real)
    for root in (app_root(), data_root()):
        try:
            if target.is_relative_to(Path(os.path.realpath(root))):
                return True
        except (OSError, ValueError):
            continue
    return False


def resolve_outside(account_id: Optional[int],
                    path: Any) -> Tuple[Optional[Dict[str, Any]], str]:
    """One file by its absolute path -> (resolved, "") or (None, why not).
    Like resolve() it fixes the content (sha256, size) at request time.
    Marked "outside" unless the path is one of the registered files.
    Refused: what is not a file, a program, anything past MAX_ADDED_BYTES
    and GigaMail's own data (tokens, approvals, logs)."""
    from gigamail.core import mail_guard
    raw = str(path or "").strip()
    real = os.path.realpath(raw)
    if not is_path(raw) or not os.path.isfile(real):
        return None, f"{raw} (no such file)"
    name = os.path.basename(real)
    if mail_guard.is_executable_name(name):
        return None, f"{raw} (a program is never attached)"
    if _is_gigamail_data(real):
        return None, f"{raw} (GigaMail's own data is never attached)"
    try:
        if os.path.getsize(real) > MAX_ADDED_BYTES:
            return None, f"{raw} (larger than 25 MB)"
        with open(real, "rb") as fh:
            data = fh.read()
    except OSError:
        return None, f"{raw} (unreadable)"
    resolved = {"name": name, "path": real, "sha256": _sha256(data), "size": len(data)}
    registered = set()
    for f in identity_reader.list_all_files(identity_paths(account_id)):
        registered.add(os.path.normcase(os.path.realpath(f["path"])))
    if os.path.normcase(real) not in registered:
        resolved["outside"] = True
    return resolved, ""
