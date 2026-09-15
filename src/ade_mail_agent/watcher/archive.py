"""Archiviazione automatica: le mail di un mittente spostate in una cartella.

Nata per idealista: ogni richiesta e ogni newsletter del portale restava
nella posta in arrivo, e la cartella idealista si era fermata al 30 agosto,
all'ultima volta che qualcuno le aveva spostate a mano.

Una mail si sposta solo quando nessuna regola ha piu' bisogno di trovarla
dov'e': IMAP cambia l'id di una mail spostata, e una bozza da rifare o una
regola che non l'ha ancora vista non la ritroverebbero. Si spostano solo le
mail arrivate dopo l'attivazione: la posta vecchia resta dov'e'.
"""
import json
import time
from typing import Any, Dict, Iterable, List

from ade_mail_agent import policy
from ade_mail_agent.core import accounts as core_accounts
from ade_mail_agent.core import mail_guard, mail_router
from ade_mail_agent.core import rules as rules_mod

from . import ingestion
from .log import _log

CHIAVE = "archivio_automatico"
# Stati dopo i quali nessuna regola torna a cercare la mail. "failed" resta
# fuori apposta: una bozza fallita la deve vedere un umano nella posta in
# arrivo, non ritrovarla sepolta in una cartella.
_CONCLUSI = {"sent", "skipped", "rejected", "expired"}
_TOP = 50
_TENTATIVI_MAX = 3
# (account, message_id) -> spostamenti falliti. Senza, una cartella sparita
# riempirebbe log e audit con lo stesso errore ogni due minuti.
_falliti: Dict[tuple, int] = {}


def voci() -> List[Dict[str, Any]]:
    try:
        dato = json.loads(core_accounts.get_setting(CHIAVE, "") or "[]")
    except Exception:
        return []
    return [v for v in dato if isinstance(v, dict)
            and v.get("cartella") and v.get("domini")]


def aggiungi(account_id: int, domini: Iterable[str], cartella: str,
             dal: float = None) -> Dict[str, Any]:
    """Attiva (o sostituisce) l'archiviazione di un account in una cartella.
    `dal` e' il momento da cui vale: di default adesso."""
    elenco = [v for v in voci()
              if not (int(v.get("account_id") or 0) == int(account_id)
                      and v.get("cartella") == cartella)]
    voce = {"account_id": int(account_id),
            "domini": sorted({str(d).strip().lower().lstrip("@")
                              for d in domini if str(d).strip()}),
            "cartella": cartella,
            "dal": float(dal if dal is not None else time.time())}
    elenco.append(voce)
    core_accounts.set_setting(CHIAVE, json.dumps(elenco))
    return voce


def del_dominio(indirizzo: str, domini: Iterable[str]) -> bool:
    """Il dominio o un suo sottodominio: quotidiano.idealista.it e' idealista,
    idealista.it.esempio.com no."""
    indirizzo = str(indirizzo or "").strip().lower()
    if "@" not in indirizzo:
        return False
    dominio = indirizzo.rsplit("@", 1)[1]
    return any(dominio == d or dominio.endswith("." + d) for d in domini)


def pronta(account_id: int, message: Dict[str, Any],
           regole: List[Dict[str, Any]], unread_days: int = 7) -> bool:
    """Nessuna regola attiva su questa casella aspetta ancora la mail.

    Una regola guarda solo le mail arrivate dopo la sua creazione ed entro
    unread_days (ingestion.poll_folder): quelle piu' vecchie non le gestira'
    mai. Aspettarle le lasciava nella posta in arrivo per sempre: e' successo
    con 80 mail dell'arretrato di idealista, tutte precedenti alla regola."""
    mid = str(message.get("id") or "")
    rs = rules_mod.store()
    arrivo = mail_router._message_datetime(str(message.get("receivedDateTime") or ""))
    adesso = time.time()
    for regola in regole:
        if int(regola["account_id"]) != int(account_id):
            continue
        if ingestion.folder_of(regola).lower() != "inbox":
            continue
        if not ingestion.matches(regola, message):
            continue
        riga = rs.get_handled(regola["rule_id"], mid)
        if riga:
            if riga.get("status") not in _CONCLUSI:
                return False
            continue
        soglia = max(float(regola.get("created_at") or 0),
                     adesso - unread_days * 86400)
        if arrivo is None or arrivo.timestamp() >= soglia:
            return False  # la regola la vedra': si aspetta
    return True


def archivia(w) -> int:
    """Una passata su ogni account configurato. Ritorna le mail spostate."""
    elenco = voci()
    if not elenco:
        return 0
    regole = rules_mod.store().active()
    spostate = 0
    for voce in elenco:
        aid = int(voce["account_id"])
        try:
            messaggi = mail_router.get_messages(
                account_id=aid, folder="inbox", top=_TOP) or []
        except Exception as e:
            _log(f"archivio, poll fallito ({aid}): {e}", w.verbose)
            continue
        for m in messaggi:
            if not isinstance(m, dict) or not m.get("id"):
                continue
            if not del_dominio(mail_guard.sender_address(m), voce["domini"]):
                continue
            arrivo = mail_router._message_datetime(
                str(m.get("receivedDateTime") or ""))
            if arrivo is None or arrivo.timestamp() < float(voce.get("dal") or 0):
                continue
            chiave = (aid, str(m["id"]))
            if _falliti.get(chiave, 0) >= _TENTATIVI_MAX:
                continue
            if not pronta(aid, m, regole, getattr(w, "unread_days", 7)):
                continue
            try:
                ok = bool(mail_router.move_to_folder(
                    aid, message_id=str(m["id"]), folder_id=voce["cartella"],
                    source_folder="INBOX"))
            except Exception as e:
                ok = False
                _log(f"archivio: errore su {m['id']}: {e}", w.verbose)
            policy.audit("auto_archive",
                         {"account_id": aid, "message_id": str(m["id"]),
                          "folder_id": voce["cartella"]},
                         "moved" if ok else "move_failed")
            if ok:
                spostate += 1
                _falliti.pop(chiave, None)
            else:
                _falliti[chiave] = _falliti.get(chiave, 0) + 1
                _log(f"archivio: {m['id']} NON spostata in {voce['cartella']}",
                     w.verbose)
    if spostate:
        _log(f"archivio: {spostate} mail spostate", w.verbose)
    return spostate
