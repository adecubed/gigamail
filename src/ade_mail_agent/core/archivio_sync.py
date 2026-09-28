# GigaMail — mail for your AI agent
# Copyright (C) 2026 Adecubed
# Licensed under the GNU AGPL v3 or later. See LICENSE.
"""Sincronizzazione continua: ogni mail che passa dal server finisce
nell'archivio, prima che il server se ne liberi.

Gira a ogni giro del watcher con un tetto di messaggi, cosi' un primo
caricamento di migliaia di mail si spalma su piu' giri invece di bloccare
le regole per mezz'ora. Da riga di comando (`gigamail archive sync`) gira
invece finche' non ha finito.

IMAP: per ogni cartella si ricorda l'ultimo UID archiviato e l'UIDVALIDITY.
Se il server cambia UIDVALIDITY si riparte da capo: i duplicati li ferma
il Message-ID, non il numero.
Graph: per ogni cartella si scorre dal piu' recente e ci si ferma alla
prima pagina gia' tutta in archivio. Il primo caricamento riprende dal
link della pagina successiva salvato come cursore.

Le bozze non si archiviano: cambiano a ogni tasto premuto e non sono
posta.
"""
import imaplib
import logging
import time
from typing import Callable, Dict, List, Optional

from . import archivio

logger = logging.getLogger("gigamail.archivio")

LIMITE_GIRO = 200          # messaggi per account a ogni giro del watcher
_LOTTO_IMAP = 20           # messaggi per singolo FETCH
_ESCLUSE = ("draft", "bozze", "template", "modelli")


def _esclusa(nome: str) -> bool:
    n = (nome or "").lower()
    return any(e in n for e in _ESCLUSE)


def _nessuno() -> None:
    return None


# ── IMAP ─────────────────────────────────────────────────────────────

def _uidvalidity(conn) -> str:
    try:
        typ, dati = conn.response("UIDVALIDITY")
        if dati and dati[0]:
            v = dati[0]
            return v.decode() if isinstance(v, bytes) else str(v)
    except Exception:
        pass
    return ""


def _uid_nuovi(conn, dopo: int) -> List[int]:
    typ, dati = conn.uid("search", None, "UID", f"{dopo + 1}:*")
    if typ != "OK" or not dati or not dati[0]:
        return []
    # "N:*" restituisce sempre almeno l'ultimo UID, anche se e' <= N.
    return sorted(u for u in (int(x) for x in dati[0].split()) if u > dopo)


def _scarica_lotto(conn, uids: List[int]):
    """[(uid, raw, internaldate_ts)] per un lotto di UID."""
    typ, dati = conn.uid("fetch", ",".join(str(u) for u in uids),
                         "(UID INTERNALDATE RFC822)")
    if typ != "OK":
        return []
    out = []
    for parte in dati or []:
        if not isinstance(parte, tuple) or len(parte) < 2:
            continue
        meta = parte[0].decode("utf-8", errors="replace") if isinstance(parte[0], bytes) else str(parte[0])
        try:
            uid = int(meta.split("UID", 1)[1].split()[0].strip("()"))
        except Exception:
            continue
        ts = None
        try:
            tt = imaplib.Internaldate2tuple(parte[0] if isinstance(parte[0], bytes) else meta.encode())
            if tt:
                ts = time.mktime(tt)
        except Exception:
            pass
        out.append((uid, parte[1], ts))
    return out


def sincronizza_imap(account_id: int, conn, *, limite: int = LIMITE_GIRO,
                     battito: Callable[[], None] = _nessuno,
                     st: Optional[archivio.ArchiveStore] = None) -> Dict[str, int]:
    """Archivia i messaggi nuovi di tutte le cartelle. `conn` e' una
    connessione IMAP gia' autenticata."""
    st = st or archivio.store()
    from . import imap_client as ic
    cartelle = ic._list_folders(conn)
    esito = {"nuovi": 0, "gia_presenti": 0, "cartelle": 0, "restano": 0}
    for cartella in cartelle:
        if _esclusa(cartella):
            continue
        typ, _dati = conn.select(f'"{cartella}"', readonly=True)
        if typ != "OK":
            continue
        esito["cartelle"] += 1
        validita = _uidvalidity(conn)
        stato = st.stato(account_id, cartella) or {}
        ultimo = int(stato.get("cursor") or 0)
        if stato and stato.get("uidvalidity") and validita and stato["uidvalidity"] != validita:
            logger.info("UIDVALIDITY cambiata in %s: si riparte da capo", cartella)
            ultimo = 0
        nuovi = _uid_nuovi(conn, ultimo)
        spazio = max(0, limite - esito["nuovi"] - esito["gia_presenti"])
        da_fare = nuovi[:spazio]
        esito["restano"] += len(nuovi) - len(da_fare)
        cursore = ultimo
        for i in range(0, len(da_fare), _LOTTO_IMAP):
            lotto = da_fare[i:i + _LOTTO_IMAP]
            for uid, raw, ts in _scarica_lotto(conn, lotto):
                # Una mail che non si salva non ferma le altre: prima una
                # sola intestazione malformata bloccava la cartella, e il
                # watcher ci ribatteva a ogni giro senza mai andare avanti.
                try:
                    _id, nuovo = st.salva(account_id, raw, folder=cartella,
                                          provider_id=str(uid), source="imap",
                                          ripiego_data=ts)
                    esito["nuovi" if nuovo else "gia_presenti"] += 1
                except Exception as e:
                    esito["errori"] = esito.get("errori", 0) + 1
                    logger.warning("archivio: %s UID %s non salvato: %s",
                                   cartella, uid, e)
            # Il cursore avanza a ogni lotto: un giro interrotto a meta'
            # riprende da qui, non da capo.
            cursore = max(lotto)
            st.aggiorna_stato(account_id, cartella, uidvalidity=validita,
                              cursor=str(cursore), complete=False)
            battito()
        st.aggiorna_stato(account_id, cartella, uidvalidity=validita,
                          cursor=str(cursore),
                          complete=len(da_fare) == len(nuovi))
    return esito


# ── GRAPH ────────────────────────────────────────────────────────────

def _cartelle_graph(get) -> List[Dict[str, str]]:
    from .mail import GRAPH_URL
    out: List[Dict[str, str]] = []
    coda = [f"{GRAPH_URL}/me/mailFolders?$top=100&includeHiddenFolders=true"]
    while coda:
        url = coda.pop()
        while url:
            r = get(url)
            for f in r.get("value", []):
                out.append({"id": f["id"], "nome": f.get("displayName") or f["id"]})
                if f.get("childFolderCount"):
                    coda.append(f"{GRAPH_URL}/me/mailFolders/{f['id']}/childFolders?$top=100")
            url = r.get("@odata.nextLink")
    return out


def sincronizza_graph(account_id: int, *, get, get_raw,
                      limite: int = LIMITE_GIRO,
                      battito: Callable[[], None] = _nessuno,
                      st: Optional[archivio.ArchiveStore] = None) -> Dict[str, int]:
    """`get(url) -> dict` e `get_raw(url) -> bytes` parlano con Graph gia'
    autenticati: passati da fuori, cosi' i test non toccano la rete."""
    from .mail import GRAPH_URL
    st = st or archivio.store()
    esito = {"nuovi": 0, "gia_presenti": 0, "cartelle": 0, "restano": 0}
    for f in _cartelle_graph(get):
        if _esclusa(f["nome"]):
            continue
        esito["cartelle"] += 1
        stato = st.stato(account_id, f["id"]) or {}
        completa = bool(stato.get("complete"))
        url = (stato.get("cursor") if not completa and stato.get("cursor") else
               f"{GRAPH_URL}/me/mailFolders/{f['id']}/messages"
               "?$select=id,receivedDateTime&$orderby=receivedDateTime desc&$top=50")
        while url:
            if esito["nuovi"] + esito["gia_presenti"] >= limite:
                esito["restano"] += 1
                if not completa:
                    st.aggiorna_stato(account_id, f["id"], cursor=url, complete=False)
                break
            pagina = get(url)
            valori = pagina.get("value", [])
            nuovi_pagina = 0
            for m in valori:
                if st.ha_provider_id(account_id, m["id"]):
                    esito["gia_presenti"] += 1
                    continue
                try:
                    raw = get_raw(f"{GRAPH_URL}/me/messages/{m['id']}/$value")
                    _id, nuovo = st.salva(account_id, raw, folder=f["nome"],
                                          provider_id=m["id"], source="graph")
                except Exception as e:
                    esito["errori"] = esito.get("errori", 0) + 1
                    logger.warning("archivio: messaggio Graph %s non salvato: %s",
                                   m["id"], e)
                    continue
                esito["nuovi" if nuovo else "gia_presenti"] += 1
                nuovi_pagina += int(nuovo)
            battito()
            url = pagina.get("@odata.nextLink")
            if completa and valori and nuovi_pagina == 0:
                # Una pagina intera gia' archiviata: il resto e' vecchio.
                break
        else:
            st.aggiorna_stato(account_id, f["id"], cursor="", complete=True)
    return esito


# ── INGRESSO ─────────────────────────────────────────────────────────

def sincronizza(account_id: int, *, limite: int = LIMITE_GIRO,
                battito: Callable[[], None] = _nessuno) -> Dict[str, int]:
    """Un account, qualunque sia il provider."""
    from . import mail_router
    a = mail_router._account(account_id)
    if not a:
        raise ValueError(f"account {account_id} non trovato")
    tipo = a.get("type", "microsoft")
    if tipo == "demo":
        return {"nuovi": 0, "gia_presenti": 0, "cartelle": 0, "restano": 0}
    if tipo == "microsoft":
        import requests

        from . import mail as ms_mail

        def get(url):
            r = requests.get(url, headers=ms_mail._headers(), timeout=60)
            r.raise_for_status()
            return r.json()

        def get_raw(url):
            r = requests.get(url, headers=ms_mail._headers(), timeout=120)
            r.raise_for_status()
            return r.content

        return sincronizza_graph(account_id, get=get, get_raw=get_raw,
                                 limite=limite, battito=battito)
    from . import imap_client as ic
    host, port, user, pwd = mail_router._imap_credentials(a)
    chiave, conn = ic._acquire_connection(host, port, user, pwd)
    rotta = False
    try:
        return sincronizza_imap(account_id, conn, limite=limite, battito=battito)
    except Exception:
        rotta = True
        raise
    finally:
        ic._release_connection(chiave, conn, mark_bad=rotta)


def sincronizza_tutto(*, limite: int = LIMITE_GIRO,
                      battito: Callable[[], None] = _nessuno) -> Dict[int, Dict[str, int]]:
    """Tutti gli account. Un account che non risponde non ferma gli altri."""
    from . import accounts as core_accounts
    esiti: Dict[int, Dict[str, int]] = {}
    for a in core_accounts.get_accounts():
        aid = int(a["id"])
        try:
            esiti[aid] = sincronizza(aid, limite=limite, battito=battito)
        except Exception as e:
            logger.warning("archivio: account %s non sincronizzato: %s", aid, e)
            esiti[aid] = {"errore": 1}
    return esiti
