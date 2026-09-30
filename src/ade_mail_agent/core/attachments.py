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
import hashlib
import hmac
import mimetypes
import re
from typing import Any, Dict, List, Optional, Tuple

from ade_mail_agent.core import accounts as core_accounts
from ade_mail_agent.core import identity_reader

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
    chieda il cliente. Il core non sa che forma abbia un codice (A.3.2 per
    un'agenzia, SKU-12 per un negozio): lo dice l'estensione. Senza
    estensioni non si legge niente e resta la lista della regola."""
    from ade_mail_agent.core import extensions
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

    Pretende una corrispondenza UNIVOCA. 'A.1.4' deve dare A.1.4.pdf, mai
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
        out.append({"name": f["name"], "path": f["path"],
                    "size_kb": round(size / 1024, 1) if size is not None else None,
                    "sha256": sha[:12] if sha else None})
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
