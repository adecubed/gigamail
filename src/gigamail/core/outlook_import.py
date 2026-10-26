# GigaMail — mail for your AI agent
# Copyright (C) 2026 Adecubed
# Licensed under the GNU AGPL v3 or later. See LICENSE.
"""Import una tantum dello storico che Outlook ha gia' tolto dal server.

Outlook, nella configurazione piu' comune, scarica la posta e dopo un paio
di settimane la cancella dal server. Da quel momento la mail esiste solo
nel suo file sul PC. Quando si installa GigaMail quello storico va
recuperato una volta, altrimenti l'archivio parte con un buco di anni: il
28/09/2026 una bolletta di gennaio era introvabile proprio per questo.

Si fa UNA volta per account, di default: il watcher, alla prima occhiata a
un account, vede che l'import non c'e' ancora stato e lo lancia in un
processo a parte (dura minuti, il watcher deve continuare a girare). Dopo,
GigaMail non chiede piu' niente a Outlook: la posta nuova arriva dal
server con la sincronizzazione continua.

Outlook non espone il MIME originale. Il messaggio si ricostruisce dalle
intestazioni internet che conserva (Message-ID, date, mittenti veri),
dal corpo e dagli allegati. Se la stessa mail e' ancora sul server, la
copia del server la sostituisce: e' quella originale.
"""
import email.utils
import logging
import mimetypes
import os
import subprocess
import sys
import tempfile
from email.message import EmailMessage
from email.parser import HeaderParser
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import archivio

logger = logging.getLogger("gigamail.outlook_import")

FONTE = "outlook"
TENTATIVI_MAX = 3

_PR_TRANSPORT_HEADERS = "http://schemas.microsoft.com/mapi/proptag/0x007D001F"
_PR_INTERNET_MESSAGE_ID = "http://schemas.microsoft.com/mapi/proptag/0x1035001F"
_PR_SMTP_ADDRESS = "http://schemas.microsoft.com/mapi/proptag/0x39FE001F"
_PR_ATTACH_DATA_BIN = "http://schemas.microsoft.com/mapi/proptag/0x37010102"
_OL_MAIL_ITEM = 43
_OL_FOLDER_MAIL = 0
_OL_TO, _OL_CC = 1, 2
_OL_BY_VALUE = 1

# Le intestazioni originali che valgono la pena: identita' del messaggio,
# persone, data, thread. Le Received e i timbri antispam no.
_INTESTAZIONI = ("Message-ID", "Date", "From", "Sender", "Reply-To", "To",
                 "Cc", "Subject", "In-Reply-To", "References")


def disponibile() -> bool:
    """Outlook classico installato su questo PC, raggiungibile via COM."""
    if sys.platform != "win32":
        return False
    try:
        import winreg
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CLASSES_ROOT,
                                       r"Outlook.Application\CLSID"))
    except Exception:
        return False
    try:
        import win32com.client  # noqa: F401
    except Exception:
        return False
    return True


# ── DA ELEMENTO DI OUTLOOK A MIME ───────────────────────────────────

def _prop(item, nome: str) -> str:
    try:
        return str(item.PropertyAccessor.GetProperty(nome) or "")
    except Exception:
        return ""


def _indirizzo(recipient) -> str:
    """L'indirizzo SMTP del destinatario.

    Chiedere ad AddressEntry costa quasi mezzo secondo a destinatario
    (misurato il 28/09 su una casella POP): si fa solo per gli indirizzi
    Exchange ("/o=..."), che sono gli unici a non essere gia' SMTP."""
    diretto = str(getattr(recipient, "Address", "") or "")
    if diretto and not diretto.lower().startswith("/o="):
        return diretto
    try:
        ae = recipient.AddressEntry
        smtp = ""
        try:
            smtp = str(ae.PropertyAccessor.GetProperty(_PR_SMTP_ADDRESS) or "")
        except Exception:
            pass
        if not smtp:
            try:
                ex = ae.GetExchangeUser()
                smtp = str(ex.PrimarySmtpAddress) if ex else ""
            except Exception:
                pass
        return smtp or str(recipient.Address or "")
    except Exception:
        return str(getattr(recipient, "Address", "") or "")


def _quando(valore) -> Optional[float]:
    try:
        return float(valore.timestamp())
    except Exception:
        return None


def eml_da_item(item, cartella_tmp: Optional[str] = None) -> Tuple[bytes, Optional[float]]:
    """(MIME, timestamp di ricezione) di un MailItem di Outlook."""
    msg = EmailMessage()
    grezze = _prop(item, _PR_TRANSPORT_HEADERS)
    originali = HeaderParser().parsestr(grezze) if grezze.strip() else None
    for h in _INTESTAZIONI:
        v = originali.get(h) if originali is not None else None
        if v:
            try:
                msg[h] = str(v).replace("\r", "").replace("\n", " ")
            except Exception:
                pass
    if not msg.get("Message-ID"):
        mid = _prop(item, _PR_INTERNET_MESSAGE_ID)
        if mid:
            msg["Message-ID"] = mid
    if not msg.get("From"):
        nome = str(getattr(item, "SenderName", "") or "")
        ind = str(getattr(item, "SenderEmailAddress", "") or "")
        if ind or nome:
            msg["From"] = email.utils.formataddr((nome, ind))
    if not msg.get("To") and not msg.get("Cc"):
        a, cc = [], []
        try:
            for r in item.Recipients:
                voce = email.utils.formataddr((str(r.Name or ""), _indirizzo(r)))
                (cc if getattr(r, "Type", _OL_TO) == _OL_CC else a).append(voce)
        except Exception:
            pass
        if a:
            msg["To"] = ", ".join(a)
        if cc:
            msg["Cc"] = ", ".join(cc)
    if not msg.get("Subject"):
        msg["Subject"] = str(getattr(item, "Subject", "") or "")
    ricevuta = _quando(getattr(item, "ReceivedTime", None)) or _quando(getattr(item, "SentOn", None))
    if not msg.get("Date") and ricevuta is not None:
        msg["Date"] = email.utils.formatdate(ricevuta, localtime=True)

    testo = str(getattr(item, "Body", "") or "")
    # HTMLBody su una mail in testo semplice o RTF costringe Outlook a
    # convertirla: e' il passaggio piu' lento dell'export. Si chiede solo
    # alle mail che in HTML ci sono nate (BodyFormat 2).
    html = ""
    try:
        formato = int(getattr(item, "BodyFormat", 2) or 2)
    except Exception:
        formato = 2
    if formato == 2:
        html = str(getattr(item, "HTMLBody", "") or "")
    msg.set_content(testo or " ")
    if html.strip():
        msg.add_alternative(html, subtype="html")

    allegati = getattr(item, "Attachments", None)
    if allegati is not None and int(getattr(allegati, "Count", 0) or 0):
        tmp = cartella_tmp or tempfile.mkdtemp(prefix="gigamail-outlook-")
        for i in range(1, int(allegati.Count) + 1):
            a = allegati.Item(i)
            if int(getattr(a, "Type", _OL_BY_VALUE) or _OL_BY_VALUE) != _OL_BY_VALUE:
                continue  # collegamenti e oggetti incorporati: non sono file
            nome = str(a.FileName or f"allegato-{i}")
            dati = _dati_allegato(a, os.path.join(tmp, f"{i}-{os.path.basename(nome)}"))
            if dati is None:
                logger.info("allegato %s non esportato", nome)
                continue
            tipo = mimetypes.guess_type(nome)[0] or "application/octet-stream"
            principale, sotto = tipo.split("/", 1)
            msg.add_attachment(dati, maintype=principale, subtype=sotto, filename=nome)
    return msg.as_bytes(), ricevuta


def _dati_allegato(a, percorso: str) -> Optional[bytes]:
    """I byte dell'allegato: prima dalla memoria, poi dal disco.

    SaveAsFile scrive un file e costava circa un secondo a mail con
    allegati. La proprieta' con i dati si legge senza passare dal disco;
    per gli allegati troppo grandi Outlook la rifiuta e si ripiega sul
    file."""
    try:
        dati = a.PropertyAccessor.GetProperty(_PR_ATTACH_DATA_BIN)
        if dati:
            return bytes(dati)
    except Exception:
        pass
    try:
        a.SaveAsFile(percorso)
        with open(percorso, "rb") as fh:
            return fh.read()
    except Exception:
        return None
    finally:
        try:
            os.remove(percorso)
        except OSError:
            pass


# ── L'IMPORT ─────────────────────────────────────────────────────────

def _caselle(ns, indirizzo: str) -> List[Any]:
    """Gli store di Outlook che contengono la posta di quell'indirizzo."""
    indirizzo = (indirizzo or "").strip().lower()
    trovati: List[Any] = []
    try:
        for acc in ns.Accounts:
            if str(acc.SmtpAddress or "").lower() == indirizzo:
                trovati.append(acc.DeliveryStore)
    except Exception:
        pass
    if not trovati:
        for s in ns.Stores:
            if indirizzo and indirizzo in str(s.DisplayName or "").lower():
                trovati.append(s)
    return trovati


_ARRIVO = ("posta in arrivo", "inbox")
_INVIATA = ("posta inviata", "sent items", "sent", "inviata")
_ULTIME = ("posta indesiderata", "junk", "spam", "posta eliminata",
           "deleted items", "cestino", "trash")


def _ordine(cartella) -> int:
    """Prima la posta in arrivo, poi le inviate, poi le altre cartelle,
    per ultimi spam e cestino. Lo storico che si cerca davvero e' in
    archivio dopo minuti: su una casella di 30.000 mail l'import intero
    dura ore, e il 28/09 la posta in arrivo era finita in coda alle
    inviate perche' avevano la stessa priorita'."""
    nome = str(getattr(cartella, "Name", "") or "").lower()
    if nome in _ARRIVO:
        return 0
    if nome in _INVIATA:
        return 1
    if any(u in nome for u in _ULTIME):
        return 3
    return 2


def _cartelle_posta(radice) -> List[Any]:
    out, coda = [], [radice]
    while coda:
        c = coda.pop()
        try:
            if int(c.DefaultItemType) == _OL_FOLDER_MAIL:
                out.append(c)
            for sotto in c.Folders:
                coda.append(sotto)
        except Exception:
            continue
    return sorted(out, key=_ordine)


def importa(account_id: int, indirizzo: str, *,
            st: Optional[archivio.ArchiveStore] = None,
            battito: Callable[[int], None] = lambda n: None) -> Dict[str, Any]:
    """Tutta la posta di quell'indirizzo che Outlook conserva sul PC."""
    import pythoncom
    import win32com.client

    st = st or archivio.store()
    pythoncom.CoInitialize()
    try:
        ns = win32com.client.Dispatch("Outlook.Application").GetNamespace("MAPI")
        caselle = _caselle(ns, indirizzo)
        if not caselle:
            return {"importati": 0, "gia_presenti": 0, "errori": 0,
                    "nota": "nessuna casella di Outlook per questo indirizzo"}
        esito = {"importati": 0, "gia_presenti": 0, "errori": 0}
        tmp = tempfile.mkdtemp(prefix="gigamail-outlook-")
        for casella in caselle:
            for cartella in _cartelle_posta(casella.GetRootFolder()):
                nome = str(cartella.Name or "")
                if any(e in nome.lower() for e in ("bozze", "draft")):
                    continue
                elementi = cartella.Items
                try:
                    # Dal piu' recente: la posta degli ultimi mesi serve
                    # subito, quella di anni fa puo' aspettare.
                    elementi.Sort("[ReceivedTime]", True)
                except Exception:
                    pass
                for item in elementi:
                    try:
                        if int(getattr(item, "Class", 0)) != _OL_MAIL_ITEM:
                            continue
                        # Gia' in archivio (dal server o da un import
                        # interrotto): si salta senza esportarlo.
                        if st.ha_chiave(account_id, _prop(item, _PR_INTERNET_MESSAGE_ID)):
                            esito["gia_presenti"] += 1
                            continue
                        raw, ts = eml_da_item(item, tmp)
                        _id, nuovo = st.salva(account_id, raw, folder=nome,
                                              source=FONTE, ripiego_data=ts)
                        esito["importati" if nuovo else "gia_presenti"] += 1
                    except Exception as e:
                        esito["errori"] += 1
                        logger.info("elemento di Outlook non importato: %s", e)
                    fatti = esito["importati"] + esito["gia_presenti"]
                    if fatti and fatti % 100 == 0:
                        battito(fatti)
        return esito
    finally:
        pythoncom.CoUninitialize()


def esegui(account_id: int) -> int:
    """Il processo lanciato dal watcher: importa e segna com'e' andata."""
    from . import accounts as core_accounts
    st = archivio.store()
    a = core_accounts.get_account_by_id(int(account_id)) or {}
    indirizzo = str(a.get("email") or "")
    st.import_segna(account_id, FONTE, "running", pid=os.getpid(),
                    detail=_tentativi(st, account_id))
    try:
        esito = importa(account_id, indirizzo, st=st,
                        battito=lambda n: st.import_segna(
                            account_id, FONTE, "running", count=n,
                            pid=os.getpid(), detail=_tentativi(st, account_id)))
    except Exception as e:
        st.import_segna(account_id, FONTE, "failed",
                        detail=f"{_tentativi(st, account_id)} {e}"[:500])
        logger.warning("import da Outlook fallito per %s: %s", account_id, e)
        return 1
    st.import_segna(account_id, FONTE, "done",
                    count=esito["importati"] + esito["gia_presenti"],
                    detail=str(esito))
    return 0


def _tentativi(st, account_id: int) -> str:
    """Il contatore dei tentativi vive in testa a `detail`: "tentativo:N"."""
    stato = st.import_stato(account_id, FONTE) or {}
    return stato.get("detail", "").split(" ", 1)[0] if str(
        stato.get("detail", "")).startswith("tentativo:") else "tentativo:0"


def _numero_tentativi(stato: Dict[str, Any]) -> int:
    d = str(stato.get("detail") or "")
    if d.startswith("tentativo:"):
        try:
            return int(d.split(" ", 1)[0].split(":", 1)[1])
        except ValueError:
            return 0
    return 0


def avvia_se_serve(account_id: int, *,
                   st: Optional[archivio.ArchiveStore] = None,
                   pid_vivo: Optional[Callable[[int], bool]] = None,
                   lancia: Optional[Callable[[List[str]], int]] = None) -> str:
    """Lancia l'import in un processo a parte, se non e' mai stato fatto.

    Ritorna cosa e' successo: 'non-disponibile', 'fatto', 'in-corso',
    'abbandonato' (troppi tentativi falliti) o 'avviato'."""
    st = st or archivio.store()
    if not disponibile():
        return "non-disponibile"
    stato = st.import_stato(account_id, FONTE) or {}
    if stato.get("status") == "done":
        return "fatto"
    if pid_vivo is None:
        from gigamail.watcher.process_state import pid_alive as pid_vivo
    if stato.get("status") == "running" and stato.get("pid") and pid_vivo(int(stato["pid"])):
        return "in-corso"
    tentativi = _numero_tentativi(stato)
    if tentativi >= TENTATIVI_MAX:
        return "abbandonato"
    comando = [sys.executable, "-m", "gigamail.cli", "archive",
               "import-outlook", "--account-id", str(int(account_id))]
    if lancia is None:
        def lancia(cmd: List[str]) -> int:
            flag = 0
            if sys.platform == "win32":
                flag = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS
            p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, creationflags=flag)
            return p.pid
    pid = lancia(comando)
    st.import_segna(account_id, FONTE, "running", pid=pid,
                    detail=f"tentativo:{tentativi + 1}")
    return "avviato"
