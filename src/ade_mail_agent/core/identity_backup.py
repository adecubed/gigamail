# GigaMail — mail for your AI agent
# Copyright (C) 2026 Adecubed
# Licensed under the GNU AGPL v3 or later. See LICENSE.
"""Storia locale dell'identity di un account.

L'identity e' cio' che rende utile una risposta automatica: cosa e' vero
dell'azienda, cosa non si promette mai, dove si tiene un appuntamento.
Si accumula una riga alla volta, spesso mentre si sta facendo altro — e
vive in una sola riga di database, sovrascritta a ogni modifica. Senza
copie, una frase riscritta male non si puo' riportare indietro e un file
perso porta via mesi di regole.

Le copie restano SEMPRE sul computer, mai nel repository: qui dentro ci
sono l'indirizzo dell'ufficio, i prezzi, il modo di trattare i clienti.
Il repository e' pubblico; questa cartella no.

Non viene salvato nulla che assomigli a una credenziale: l'identity non
ne contiene, e i campi copiati sono elencati uno per uno invece di
prendere la riga intera, cosi' se un domani la tabella ne guadagnasse
uno non finirebbe qui per inerzia.
"""
import json
import os
import time
from typing import Any, Dict, List, Optional

CAMPI = ("who_am_i", "what_i_do", "tone", "key_info", "file_paths")


def cartella(root: Optional[str] = None) -> str:
    """Dove vivono le copie. Sotto app_root(), quindi in %APPDATA%\\ADE su
    Windows: fuori dal repository, per costruzione."""
    if root:
        base = root
    else:
        from ade_mail_agent.core.data_paths import app_root
        base = os.path.join(str(app_root()), "identity-backup")
    os.makedirs(base, exist_ok=True)
    return base


def _contenuto(identity: Dict[str, Any]) -> Dict[str, Any]:
    return {c: identity.get(c) for c in CAMPI}


def snapshot(account_id: int, identity: Dict[str, Any],
             root: Optional[str] = None) -> Optional[str]:
    """Salva una copia datata, se e' cambiato qualcosa.

    Ritorna il percorso scritto, o None se l'identity e' identica
    all'ultima copia: senza questo controllo ogni avvio del watcher
    riempirebbe la cartella di file uguali e la storia diventerebbe
    illeggibile proprio quando serve.
    """
    base = cartella(root)
    corpo = _contenuto(identity)
    precedenti = storia(account_id, root)
    if precedenti:
        try:
            with open(precedenti[-1], encoding="utf-8") as f:
                if json.load(f).get("identity") == corpo:
                    return None
        except Exception:
            pass  # copia illeggibile: meglio scriverne una nuova
    # Il nome ha la risoluzione al secondo: due modifiche nello stesso
    # secondo — uno script che ne fa piu' d'una — si sovrascriverebbero,
    # perdendo proprio la storia che queste copie esistono per tenere.
    radice = f"account-{int(account_id)}-{time.strftime('%Y%m%d-%H%M%S')}"
    # Il progressivo c'e' SEMPRE, anche sul primo file del secondo: con
    # nomi di forma diversa l'ordine alfabetico mette '-02.json' prima di
    # '.json' (il trattino precede il punto), e la copia piu' recente
    # risulterebbe la piu' vecchia proprio a chi cerca l'ultima.
    n = 1
    percorso = os.path.join(base, f"{radice}-{n:02d}.json")
    while os.path.exists(percorso):
        n += 1
        percorso = os.path.join(base, f"{radice}-{n:02d}.json")
    with open(percorso, "w", encoding="utf-8") as f:
        json.dump({"account_id": int(account_id),
                   "salvata_il": time.strftime("%Y-%m-%d %H:%M:%S"),
                   "identity": corpo}, f, ensure_ascii=False, indent=1)
    return percorso


def storia(account_id: int, root: Optional[str] = None) -> List[str]:
    """Le copie di un account, dalla piu' vecchia alla piu' recente."""
    base = cartella(root)
    prefisso = f"account-{int(account_id)}-"
    try:
        nomi = [n for n in os.listdir(base)
                if n.startswith(prefisso) and n.endswith(".json")]
    except Exception:
        return []
    return [os.path.join(base, n) for n in sorted(nomi)]


def leggi(percorso: str) -> Dict[str, Any]:
    with open(percorso, encoding="utf-8") as f:
        return json.load(f)


def pota(account_id: int, tieni: int = 100,
         root: Optional[str] = None) -> int:
    """Tiene le ultime `tieni` copie. Ritorna quante ne ha tolte."""
    copie = storia(account_id, root)
    da_togliere = copie[:-tieni] if tieni > 0 else []
    tolte = 0
    for p in da_togliere:
        try:
            os.remove(p)
            tolte += 1
        except Exception:
            pass
    return tolte
