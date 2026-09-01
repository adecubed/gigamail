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
import mimetypes
import os
from typing import Any, Dict, List, Optional, Tuple

from ade_mail_agent.core import accounts as core_accounts
from ade_mail_agent.core import identity_reader


def identity_paths(account_id: Optional[int]) -> List[str]:
    aid = account_id or (core_accounts.get_active_account() or {}).get("id")
    if not aid:
        return []
    return core_accounts.get_identity(aid).get("file_paths") or []


def resolve(account_id: Optional[int],
            names: Optional[List[str]]) -> Tuple[List[Dict[str, str]], List[str]]:
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

    Ritorna (risolti, mancanti); i mancanti fermano il chiamante.
    """
    if not names:
        return [], []
    paths = identity_paths(account_id)
    risolti: List[Dict[str, str]] = []
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
            risolti.append({"name": f["name"], "path": f["path"]})
        elif not scelti:
            mancanti.append(n)
        else:
            mancanti.append(
                f"{n} (ambiguo: " + ", ".join(f["name"] for f in scelti[:5]) + ")")
    return risolti, mancanti


def preview(risolti: Optional[List[Dict[str, str]]]) -> List[Dict[str, Any]]:
    """Cosa l'umano vede prima di approvare: nome, percorso e peso reale
    di ogni file che uscira'."""
    out = []
    for f in risolti or []:
        try:
            kb = round(os.path.getsize(f["path"]) / 1024, 1)
        except Exception:
            kb = None
        out.append({"name": f["name"], "path": f["path"], "size_kb": kb})
    return out


def payload(risolti: Optional[List[Dict[str, str]]]) -> List[Dict[str, str]]:
    """Legge i file al momento dell'INVIO, non dell'anteprima, e li porta
    nel formato di mail_router: [{name, data_b64, type}]."""
    out = []
    for f in risolti or []:
        with open(f["path"], "rb") as fh:
            data = fh.read()
        tipo = mimetypes.guess_type(f["name"])[0] or "application/octet-stream"
        out.append({"name": f["name"], "type": tipo,
                    "data_b64": base64.b64encode(data).decode("ascii")})
    return out
