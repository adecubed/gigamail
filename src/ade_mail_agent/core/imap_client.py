"""
imap_client.py — Lettura e invio mail via IMAP/SMTP.
Discovery automatica cartelle IMAP. Compatibile con Aruba, Gmail, Outlook,
Libero, custom.
"""
import imaplib
import smtplib
import email
import email.header
import ssl
import re
import os
import time
import threading
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import parsedate_to_datetime
from typing import List, Dict, Optional, Tuple

from .addresses import split_addresses
# Alias canonici → nomi IMAP comuni
_FOLDER_ALIASES = {
    "inbox": ["INBOX", "Inbox"],
    "sent": [
        "Sent",
        "SENT",
        "Sent Messages",
        "Sent Items",
        "SentItems",
        "[Gmail]/Sent Mail",
    ],
    "drafts": ["Drafts", "DRAFTS", "Draft", "[Gmail]/Drafts"],
    "trash": [
        "Trash",
        "TRASH",
        "Deleted Items",
        "DeletedItems",
        "Deleted Messages",
        "[Gmail]/Trash",
    ],
    "deleteditems": [
        "Deleted Items",
        "DeletedItems",
        "Trash",
        "TRASH",
        "[Gmail]/Trash",
    ],
    "junk": [
        "Junk",
        "JUNK",
        "Spam",
        "SPAM",
        "INBOX.SPAM",
        "Junk Email",
        "Junk Mail",
        "Bulk Mail",
        "Posta indesiderata",
        "Indesiderata",
        "[Gmail]/Spam",
    ],
    "junkemail": [
        "Junk",
        "Junk Email",
        "Spam",
        "SPAM",
        "INBOX.SPAM",
        "Bulk Mail",
        "Posta indesiderata",
        "Indesiderata",
        "[Gmail]/Spam",
    ],
    "inboxspam": [
        "INBOX.SPAM",
        "Spam",
        "SPAM",
        "Junk",
        "JUNK",
        "Junk Email",
        "[Gmail]/Spam",
    ],
    "spam": [
        "INBOX.SPAM",
        "Spam",
        "SPAM",
        "Junk",
        "JUNK",
        "[Gmail]/Spam",
    ],
    "archive": ["Archive", "ARCHIVE", "All Mail", "[Gmail]/All Mail"],
}

_IMAP_DEBUG = os.environ.get("ADE_MAIL_IMAP_DEBUG", "0") in ("1", "true", "True")
_IMAP_TIMING = os.environ.get("ADE_MAIL_TIMING", "0") in ("1", "true", "True")
_IMAP_CONN_TTL = int(os.environ.get("ADE_MAIL_IMAP_CONN_TTL", "180"))
_IMAP_CONN_CACHE: Dict[Tuple[str, int, str, str], Dict[str, object]] = {}
_IMAP_CONN_CACHE_LOCK = threading.Lock()


def _imap_debug_log(message: str) -> None:
    if _IMAP_DEBUG:
        print(f"[IMAP DEBUG] {message}")


def _imap_timing_log(label: str, started_at: float, extra: str = "") -> None:
    if _IMAP_TIMING:
        elapsed_ms = int((time.perf_counter() - started_at) * 1000)
        suffix = f" {extra}" if extra else ""
        print(f"[IMAP TIMING] {label}={elapsed_ms}ms{suffix}")


def _connection_key(imap_host: str, imap_port: int, email_addr: str, password: str) -> Tuple[str, int, str, str]:
    return (str(imap_host or ""), int(imap_port or 993), str(email_addr or ""), str(password or ""))


def _safe_decode(data: bytes, charset: str = "utf-8") -> str:
    """
    Decodifica bytes provando charset dichiarato -> utf-8 -> latin-1.
    Gestisce charset non standard (es. 'unknown-8bit') che fanno esplodere
    .decode() con LookupError prima ancora di errors='replace'.
    """
    if not isinstance(data, bytes):
        return str(data or "")
    for enc in (charset or "utf-8", "utf-8", "latin-1"):
        try:
            return data.decode(enc, errors="replace")
        except (LookupError, ValueError):
            continue
    return data.decode("latin-1", errors="replace")


def _hdr_str(value) -> str:
    """Coerce un valore header a str: msg.get() puo' restituire
    email.header.Header per header malformati/non-ASCII grezzi."""
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    try:
        return str(value)
    except Exception:
        return ""


def _decode_header(value) -> str:
    parts = email.header.decode_header(_hdr_str(value))
    decoded = []
    for part, charset in parts:
        if isinstance(part, bytes):
            decoded.append(_safe_decode(part, charset))
        else:
            decoded.append(str(part))
    return " ".join(decoded)
def _get_body(msg):
    html_body = ""
    plain_body = ""
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            cd = str(part.get("Content-Disposition", ""))
            if "attachment" in cd:
                continue
            if ct == "text/html" and not html_body:
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    html_body = _safe_decode(payload, charset).strip()
            elif ct == "text/plain" and not plain_body:
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    plain_body = _safe_decode(payload, charset).strip()
    else:
        payload = msg.get_payload(decode=True)
        charset = msg.get_content_charset() or "utf-8"
        raw = _safe_decode(payload, charset).strip() if payload else ""
        if "<html" in raw.lower() or "<!doctype" in raw.lower():
            html_body = raw
        else:
            plain_body = raw
    if html_body:
        return html_body, "html"
    return plain_body, "text"
_IMAP_CONNECT_TIMEOUT = 10   # secondi — timeout connessione SSL
_IMAP_MAX_RETRIES     = 2    # tentativi in caso di timeout


def _connect(
    imap_host: str,
    imap_port: int,
    email_addr: str,
    password: str,
    timeout: int = _IMAP_CONNECT_TIMEOUT,
) -> imaplib.IMAP4_SSL:
    """
    Apre connessione IMAP con timeout esplicito e retry automatico.
    Evita hang da WinError 10060 quando il server non risponde.
    """
    started = time.perf_counter()
    last_exc: Optional[Exception] = None

    for attempt in range(1, _IMAP_MAX_RETRIES + 1):
        try:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE

            # Imposta timeout a livello socket PRIMA della connessione SSL
            # per evitare hang su server lenti o irraggiungibili
            import socket as _socket
            old_timeout = _socket.getdefaulttimeout()
            _socket.setdefaulttimeout(timeout)
            try:
                conn = imaplib.IMAP4_SSL(imap_host, imap_port, ssl_context=ctx)
            finally:
                _socket.setdefaulttimeout(old_timeout)

            conn.socket().settimeout(timeout)
            conn.login(email_addr, password)
            _imap_timing_log("connect_login", started, f"email={email_addr} attempt={attempt}")
            return conn

        except (TimeoutError, OSError, imaplib.IMAP4.error) as e:
            last_exc = e
            _imap_debug_log(f"_connect attempt {attempt}/{_IMAP_MAX_RETRIES} failed: {e} ({email_addr})")
            if attempt < _IMAP_MAX_RETRIES:
                time.sleep(1)  # breve pausa prima del retry

    raise ConnectionError(
        f"IMAP connection failed after {_IMAP_MAX_RETRIES} attempts "
        f"({email_addr}@{imap_host}:{imap_port}): {last_exc}"
    )


def _close_conn_safely(conn: Optional[imaplib.IMAP4_SSL]) -> None:
    if not conn:
        return
    try:
        conn.logout()
    except Exception:
        try:
            conn.shutdown()
        except Exception:
            pass


def _is_connection_alive(conn: Optional[imaplib.IMAP4_SSL]) -> bool:
    if not conn:
        return False
    try:
        typ, _ = conn.noop()
        return typ == "OK"
    except Exception:
        return False


def _prune_imap_cache() -> None:
    now = time.time()
    stale_keys: List[Tuple[str, int, str, str]] = []
    for key, entry in list(_IMAP_CONN_CACHE.items()):
        last_used = float(entry.get("last_used", 0) or 0)
        conn = entry.get("conn")
        if now - last_used > _IMAP_CONN_TTL:
            stale_keys.append(key)
            _close_conn_safely(conn if isinstance(conn, imaplib.IMAP4_SSL) else None)
    for key in stale_keys:
        _IMAP_CONN_CACHE.pop(key, None)


def _acquire_connection(
    imap_host: str,
    imap_port: int,
    email_addr: str,
    password: str,
    force_new: bool = False,
) -> Tuple[Tuple[str, int, str, str], imaplib.IMAP4_SSL]:
    key = _connection_key(imap_host, imap_port, email_addr, password)
    # imaplib non e thread-safe: condividere lo stesso socket tra richieste
    # parallele provoca risposte interleaved, LOGOUT inattesi e socket EOF.
    # Qui privilegiamo stabilita e isolamento: ogni operazione usa una
    # connessione dedicata.
    conn = _connect(imap_host, imap_port, email_addr, password)
    _imap_debug_log(f"acquire_connection isolated-login email={email_addr} host={imap_host}:{imap_port}")
    return key, conn


def _release_connection(conn_key: Tuple[str, int, str, str], conn: Optional[imaplib.IMAP4_SSL], mark_bad: bool = False) -> None:
    _close_conn_safely(conn if isinstance(conn, imaplib.IMAP4_SSL) else None)


def _extract_mailbox_name_from_list_line(decoded: str) -> str:
    """
    Estrae il nome mailbox da una riga IMAP LIST.
    Gestisce sia formati tipo:
      (\\HasNoChildren) "/" "Sent"
    sia formati tipo:
      (\\HasNoChildren \\Junk) "." INBOX.SPAM
    """
    text = str(decoded or "").strip()
    if not text:
        return ""

    # Togli il blocco flags iniziale.
    after_flags = re.sub(r"^\([^)]*\)\s*", "", text).strip()
    if not after_flags:
        return ""

    # Rimuovi il delimitatore (spesso "." o "/"), quotato o non quotato.
    if after_flags.startswith('"'):
        end_quote = after_flags.find('"', 1)
        if end_quote != -1:
            after_flags = after_flags[end_quote + 1 :].strip()
    else:
        parts = after_flags.split(None, 1)
        if len(parts) == 2:
            after_flags = parts[1].strip()

    mailbox = after_flags.strip()
    if mailbox.startswith('"') and mailbox.endswith('"') and len(mailbox) >= 2:
        mailbox = mailbox[1:-1]
    return mailbox.strip()


def _list_folders(conn: imaplib.IMAP4_SSL) -> List[str]:
    """Elenca tutte le cartelle IMAP reali del server."""
    try:
        _, folders = conn.list()
        names: List[str] = []
        for f in folders:
            if not f:
                continue
            decoded = f.decode("utf-8", errors="replace") if isinstance(f, bytes) else str(f)
            name = _extract_mailbox_name_from_list_line(decoded)
            if name:
                names.append(name)
        return names
    except Exception:
        return []


def _list_folder_entries(conn: imaplib.IMAP4_SSL) -> List[Dict[str, str]]:
    """
    Restituisce una vista più ricca delle mailbox IMAP:
    - name: nome cartella
    - raw: riga LIST completa
    - flags: blocco flag/attribute se presente
    """
    try:
        _, folders = conn.list()
        entries: List[Dict[str, str]] = []
        for item in folders or []:
            if not item:
                continue
            decoded = item.decode("utf-8", errors="replace") if isinstance(item, bytes) else str(item)
            name = _extract_mailbox_name_from_list_line(decoded)
            flags_match = re.match(r"\(([^)]*)\)", decoded)
            flags = flags_match.group(1) if flags_match else ""
            entries.append({"name": name, "raw": decoded, "flags": flags})
        return entries
    except Exception:
        return []


def _special_use_tokens_for_key(key: str) -> List[str]:
    mapping = {
        "junk": ["\\junk", "\\spam"],
        "junkemail": ["\\junk", "\\spam"],
        "trash": ["\\trash"],
        "deleteditems": ["\\trash"],
        "sent": ["\\sent"],
        "drafts": ["\\drafts"],
        "archive": ["\\archive", "\\all"],
        "inbox": ["\\inbox"],
    }
    return mapping.get(key, [])


def _uid_search(conn: imaplib.IMAP4_SSL, *criteria: str) -> List[bytes]:
    try:
        typ, data = conn.uid("search", "UTF-8", *criteria)
        if typ != "OK" or not data or not data[0]:
            return []
        return data[0].split()
    except Exception:
        pass
    # Fallback senza charset (alcuni server non supportano UTF-8 search)
    try:
        typ, data = conn.uid("search", None, *criteria)
        if typ != "OK" or not data or not data[0]:
            return []
        return data[0].split()
    except Exception:
        return []

def get_all_uids(
    imap_host: str,
    imap_port: int,
    email_addr: str,
    password: str,
    folder: str = "INBOX",
) -> List[str]:
    """Ritorna tutti gli UID della cartella usando fetch sequenziale su range completo."""
    # Forza connessione fresca — il pool può avere stato stale
    conn_key, conn = _acquire_connection(imap_host, imap_port, email_addr, password)
    try:
        conn.check()
    except Exception:
        _release_connection(conn_key, conn, mark_bad=True)
        conn_key, conn = _acquire_connection(imap_host, imap_port, email_addr, password)
    bad_conn = False
    try:
        folder_str = f'"{folder}"' if " " in folder else folder
        typ, select_data = conn.select(folder_str, readonly=True)
        print(f"[IMAP get_all_uids] SELECT {folder_str} → typ={typ} data={select_data}")
        if typ != "OK":
            return []

        # Numero totale messaggi dalla risposta SELECT
        try:
            total = int(select_data[0].decode()) if select_data and select_data[0] else 0
        except Exception:
            total = 0

        if total == 0:
            return []

        print(f"[IMAP get_all_uids] {folder}: {total} messaggi totali")

        # Fetch UID di tutti i messaggi per sequence range 1:*
        # Più affidabile di SEARCH ALL su server che limitano i risultati
        all_uids = []
        BATCH = 500
        for start in range(1, total + 1, BATCH):
            end = min(start + BATCH - 1, total)
            try:
                typ2, data2 = conn.fetch(f"{start}:{end}", "(UID)")
                if typ2 != "OK" or not data2:
                    continue
                for item in data2:
                    if not item or item == b")":
                        continue
                    raw = item.decode("utf-8", errors="replace") if isinstance(item, bytes) else str(item)
                    m = re.search(r"UID\s+(\d+)", raw, re.IGNORECASE)
                    if m:
                        all_uids.append(m.group(1))
            except Exception as e:
                print(f"[IMAP get_all_uids] batch {start}:{end} error: {e}")
                continue

        print(f"[IMAP get_all_uids] {folder}: {len(all_uids)} UID recuperati")
        return all_uids

    except Exception as e:
        bad_conn = True
        print(f"[IMAP get_all_uids] error: {e}")
        return []
    finally:
        _release_connection(conn_key, conn, mark_bad=bad_conn)


def fetch_messages_by_uids(
    imap_host: str,
    imap_port: int,
    email_addr: str,
    password: str,
    uids: List[str],
    folder: str = "INBOX",
) -> List[Dict]:
    """Fetcha headers di una lista di UID. Usato per indicizzazione batch."""
    if not uids:
        return []
    conn_key, conn = _acquire_connection(imap_host, imap_port, email_addr, password)
    bad_conn = False
    try:
        conn.select(f'"{folder}"' if " " in folder else folder)
        results = []
        for uid in uids:
            try:
                _, msg_data = _uid_fetch(conn, uid, "(RFC822.HEADER)")
                if not msg_data or not msg_data[0] or not isinstance(msg_data[0], tuple):
                    continue
                raw = msg_data[0][1]
                msg = email.message_from_bytes(raw)
                from_raw = _hdr_str(msg.get("From", ""))
                name = _decode_header(from_raw.split("<")[0].strip())
                addr = (
                    from_raw.split("<")[1].rstrip(">").strip()
                    if "<" in from_raw
                    else from_raw.strip()
                )
                body, _ = _get_body(msg)
                preview = re.sub(r"<[^>]+>", " ", body or "")
                preview = re.sub(r"\s+", " ", preview).strip()[:500]
                results.append({
                    "id": uid,
                    "subject": _decode_header(msg.get("Subject", "")),
                    "from": {"emailAddress": {"name": name, "address": addr}},
                    "toRecipients": _parse_addr_list(_decode_header(msg.get("To", ""))),
                    "receivedDateTime": msg.get("Date", ""),
                    "bodyPreview": preview,
                    "folder": folder,
                    "isRead": True,
                })
            except Exception:
                continue
        return results
    except Exception:
        bad_conn = True
        return []
    finally:
        _release_connection(conn_key, conn, mark_bad=bad_conn)


def _uid_recent_ids(conn: imaplib.IMAP4_SSL, top: int) -> List[bytes]:
    """
    Prova a ottenere direttamente gli UID più recenti con SORT.
    Fallback a SEARCH ALL se il server non supporta SORT.
    """
    try:
        typ, data = conn.uid("SORT", "(REVERSE DATE)", "UTF-8", "ALL")
        if typ == "OK" and data and data[0]:
            ordered = data[0].split()
            return ordered[:top]
    except Exception:
        pass

    ids = _uid_search(conn, "ALL")
    if not ids:
        return []
    return ids[-top:][::-1]


def _fetch_recent_headers_by_sequence(conn: imaplib.IMAP4_SSL, top: int, total: Optional[int] = None) -> List[Dict[str, str]]:
    """
    Percorso veloce stile client desktop:
    dopo SELECT, usa il numero totale di messaggi per fetchare solo l'ultima finestra
    invece di fare SEARCH ALL su tutta la mailbox.
    """
    try:
        if total is None:
            typ, count_data = conn.select()
            if typ != "OK" or not count_data or not count_data[0]:
                return []
            total = int((count_data[0] or b"0").decode(errors="replace"))
        if total <= 0:
            return []
        # Nelle cartelle custom i messaggi possono essere stati spostati in blocco
        # molto tempo dopo la ricezione. Se guardiamo solo gli ultimi N record
        # fisici della mailbox rischiamo di vedere mail vecchie ma spostate di recente,
        # saltando quelle davvero piu recenti per data. Per questo leggiamo una
        # finestra piu ampia e poi ordiniamo per Date a valle.
        window = min(total, max(max(1, top) * 5, 100))
        start = max(1, total - window + 1)
        query = "(UID FLAGS BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE CONTENT-TYPE)])"
        typ, msg_data = conn.fetch(f"{start}:{total}", query)
        if typ != "OK" or not msg_data:
            return []

        items: List[Dict[str, str]] = []
        for part in msg_data:
            if not isinstance(part, tuple) or len(part) < 2:
                continue
            meta_raw, header_raw = part
            if not isinstance(header_raw, (bytes, bytearray)):
                continue
            meta = meta_raw.decode("utf-8", errors="replace") if isinstance(meta_raw, bytes) else str(meta_raw)
            uid_match = re.search(r"UID\s+(\d+)", meta, re.IGNORECASE)
            if not uid_match:
                continue
            items.append(
                {
                    "uid": uid_match.group(1),
                    "raw": bytes(header_raw),
                    "meta": meta,
                }
            )
        items.reverse()
        return items[:window]
    except Exception:
        return []


def _uid_fetch(conn: imaplib.IMAP4_SSL, uid: str, query: str):
    return conn.uid("fetch", str(uid), query)


def _uid_exists_in_selected_folder(conn: imaplib.IMAP4_SSL, uid: str) -> bool:
    try:
        _, data = _uid_fetch(conn, uid, "(RFC822.HEADER)")
        return bool(data and data[0] is not None and data[0] != b"")
    except Exception:
        return False


def _uid_move(conn: imaplib.IMAP4_SSL, uid: str, dest_folder: str) -> bool:
    """
    Prova a usare l'estensione IMAP MOVE via UID.
    Alcuni server la supportano nativamente ed è più affidabile di COPY+DELETE.
    """
    try:
        typ, data = conn.uid("MOVE", str(uid), f'"{dest_folder}"')
        _imap_debug_log(f"UID MOVE uid={uid} dest={dest_folder} typ={typ} data={data}")
        return typ == "OK"
    except Exception as e:
        _imap_debug_log(f"UID MOVE uid={uid} dest={dest_folder} exception={e}")
        return False


def debug_folders(
    imap_host: str,
    imap_port: int,
    email_addr: str,
    password: str,
) -> Dict[str, object]:
    """
    Diagnostica cartelle IMAP reali del server per capire come sono esposte
    Spam/Junk/Trash/Sent/Drafts.
    """
    conn = _connect(imap_host, imap_port, email_addr, password)
    try:
        entries = _list_folder_entries(conn)
        result_entries: List[Dict[str, object]] = []
        for entry in entries:
            name = str(entry.get("name") or "")
            flags = str(entry.get("flags") or "")
            matches = []
            low_name = name.lower().replace(" ", "").replace("_", "").replace("-", "")
            low_flags = flags.lower()
            for key in ("inbox", "junk", "trash", "sent", "drafts", "archive"):
                alias_match = any(
                    low_name == alias.lower().replace(" ", "").replace("_", "").replace("-", "")
                    or low_name in alias.lower().replace(" ", "").replace("_", "").replace("-", "")
                    or alias.lower().replace(" ", "").replace("_", "").replace("-", "") in low_name
                    for alias in _FOLDER_ALIASES.get(key, [])
                )
                flag_match = any(token in low_flags for token in _special_use_tokens_for_key(key))
                if alias_match or flag_match:
                    matches.append(key)
            result_entries.append(
                {
                    "name": name,
                    "flags": flags,
                    "raw": entry.get("raw", ""),
                    "matches": matches,
                }
            )
        candidates = {}
        for key in ("junk", "trash", "sent", "drafts", "archive"):
            try:
                candidates[key] = _resolve_folder_strict(conn, key)
            except Exception:
                candidates[key] = None
        return {
            "email": email_addr,
            "entries": result_entries,
            "candidates": candidates,
        }
    finally:
        try:
            conn.logout()
        except Exception:
            pass


def list_folders(
    imap_host: str,
    imap_port: int,
    email_addr: str,
    password: str,
) -> List[Dict[str, object]]:
    conn_key, conn = _acquire_connection(imap_host, imap_port, email_addr, password)
    bad_conn = False
    try:
        items: List[Dict[str, object]] = []
        for entry in _list_folder_entries(conn):
            name = str(entry.get("name") or "").strip()
            if not name:
                continue
            items.append(
                {
                    "id": name,
                    "name": name,
                    "displayName": _imap_folder_display_name(name),
                    "flags": str(entry.get("flags") or ""),
                }
            )
        return items
    except Exception:
        bad_conn = True
        raise
    finally:
        _release_connection(conn_key, conn, mark_bad=bad_conn)


def _imap_folder_display_name(name: str) -> str:
    raw = str(name or "").strip()
    if not raw:
        return raw
    upper = raw.upper()
    if upper.startswith("INBOX."):
        return raw[6:] or raw
    if upper.startswith("INBOX/"):
        return raw[6:] or raw
    return raw


def _guess_imap_create_prefix(conn: imaplib.IMAP4_SSL) -> str:
    """
    Alcuni provider (es. Aruba/Dovecot) accettano CREATE solo sotto un namespace
    tipo INBOX.<Nome>. Proviamo a dedurlo dalle cartelle già presenti.
    """
    try:
        for entry in _list_folder_entries(conn):
            name = str(entry.get("name") or "").strip()
            if not name or name.upper() == "INBOX":
                continue
            if name.upper().startswith("INBOX."):
                return "INBOX."
            if name.upper().startswith("INBOX/"):
                return "INBOX/"
    except Exception:
        pass
    return ""


def create_folder(
    imap_host: str,
    imap_port: int,
    email_addr: str,
    password: str,
    name: str,
) -> Dict[str, object]:
    conn_key, conn = _acquire_connection(imap_host, imap_port, email_addr, password)
    bad_conn = False
    try:
        clean_name = str(name or "").strip()
        if not clean_name:
            raise ValueError("Nome cartella mancante")

        candidates = [clean_name]
        prefix = _guess_imap_create_prefix(conn)
        if prefix and not clean_name.upper().startswith(prefix.upper()):
            candidates.append(f"{prefix}{clean_name}")

        last_error = None
        for candidate in candidates:
            typ, data = conn.create(f'"{candidate}"')
            if typ == "OK":
                return {
                    "id": candidate,
                    "name": candidate,
                    "displayName": _imap_folder_display_name(candidate),
                    "created": True,
                }
            data_text = " ".join(
                item.decode("utf-8", errors="replace") if isinstance(item, bytes) else str(item)
                for item in (data or [])
            )
            if "ALREADYEXISTS" in data_text.upper():
                return {
                    "id": candidate,
                    "name": candidate,
                    "displayName": _imap_folder_display_name(candidate),
                    "created": False,
                    "already_exists": True,
                }
            last_error = data

        raise ValueError(f"Creazione cartella fallita: {last_error}")
    except Exception:
        bad_conn = True
        raise
    finally:
        _release_connection(conn_key, conn, mark_bad=bad_conn)


def delete_folder(
    imap_host: str,
    imap_port: int,
    email_addr: str,
    password: str,
    name: str,
) -> bool:
    conn_key, conn = _acquire_connection(imap_host, imap_port, email_addr, password)
    bad_conn = False
    try:
        target = str(name or "").strip()
        if not target:
            raise ValueError("Nome cartella mancante")
        typ, data = conn.delete(f'"{target}"')
        if typ == "OK":
            return True
        data_text = " ".join(
            item.decode("utf-8", errors="replace") if isinstance(item, bytes) else str(item)
            for item in (data or [])
        )
        raise ValueError(f"Eliminazione cartella fallita: {data_text or data}")
    except Exception:
        bad_conn = True
        raise
    finally:
        _release_connection(conn_key, conn, mark_bad=bad_conn)


def _resolve_folder(conn: imaplib.IMAP4_SSL, folder: str) -> str:
    """
    Dato un nome canonico (es. 'sent', 'SENT', 'Sent'),
    restituisce il nome IMAP reale supportato dal server.
    Prima prova il nome diretto, poi gli alias, poi fuzzy match.
    """
    key = folder.lower().replace(" ", "").replace("_", "").replace("-", "")
    # Prova il nome diretto
    status, _ = conn.select(f'"{folder}"')
    if status == "OK":
        return folder
    # Prova alias canonici
    candidates = list(_FOLDER_ALIASES.get(key, []))
    # Aggiungi anche varianti case
    candidates += [folder.capitalize(), folder.upper(), folder.lower()]
    real_folders = _list_folders(conn)
    for candidate in candidates:
        if candidate in real_folders:
            status, _ = conn.select(f'"{candidate}"')
            if status == "OK":
                return candidate
    # Fuzzy: cerca sottostringa case-insensitive
    key_lower = key
    for rf in real_folders:
        rf_clean = rf.lower().replace(" ", "").replace("_", "").replace("-", "")
        if key_lower in rf_clean or rf_clean in key_lower:
            status, _ = conn.select(f'"{rf}"')
            if status == "OK":
                return rf
    # Fallback INBOX
    conn.select("INBOX")
    return "INBOX"


def _resolve_folder_strict(conn: imaplib.IMAP4_SSL, folder: str) -> Optional[str]:
    """
    Variante stretta di _resolve_folder:
    restituisce il nome IMAP reale solo se la cartella esiste davvero ed è selezionabile.
    Non fa fallback silenzioso a INBOX.
    """
    key = folder.lower().replace(" ", "").replace("_", "").replace("-", "")

    status, _ = conn.select(f'"{folder}"')
    if status == "OK":
        return folder

    candidates = list(_FOLDER_ALIASES.get(key, []))
    candidates += [folder.capitalize(), folder.upper(), folder.lower()]
    real_folders = _list_folders(conn)
    folder_entries = _list_folder_entries(conn)

    for candidate in candidates:
        if candidate in real_folders:
            status, _ = conn.select(f'"{candidate}"')
            if status == "OK":
                return candidate

    special_tokens = _special_use_tokens_for_key(key)
    if special_tokens:
        for entry in folder_entries:
            flags_low = str(entry.get("flags") or "").lower()
            name = str(entry.get("name") or "")
            if any(token in flags_low for token in special_tokens):
                status, _ = conn.select(f'"{name}"')
                if status == "OK":
                    return name

    for rf in real_folders:
        rf_clean = rf.lower().replace(" ", "").replace("_", "").replace("-", "")
        if key in rf_clean or rf_clean in key:
            status, _ = conn.select(f'"{rf}"')
            if status == "OK":
                return rf

    return None


def _append_to_sent_folder(
    imap_host: str,
    imap_port: int,
    email_addr: str,
    password: str,
    mime_bytes: bytes,
) -> bool:
    conn: Optional[imaplib.IMAP4_SSL] = None
    try:
        conn = _connect(imap_host, imap_port, email_addr, password)
        sent_folder = _resolve_folder_strict(conn, "sent")
        if not sent_folder:
            _imap_debug_log("append_to_sent skipped sent-folder-not-found")
            return False
        append_res = conn.append(f'"{sent_folder}"', "\\Seen", None, mime_bytes)
        ok = bool(append_res and append_res[0] == "OK")
        _imap_debug_log(f"append_to_sent folder={sent_folder!r} result={append_res}")
        return ok
    except Exception as e:
        _imap_debug_log(f"append_to_sent exception={e}")
        return False
    finally:
        _close_conn_safely(conn)


def get_messages(
    imap_host: str,
    imap_port: int,
    email_addr: str,
    password: str,
    folder: str = "INBOX",
    top: int = 20,
) -> List[Dict]:
    started_total = time.perf_counter()
    requested = (folder or "INBOX").strip()

    for attempt in range(2):
        conn_key = None
        conn = None
        bad_conn = False
        try:
            conn_key, conn = _acquire_connection(
                imap_host,
                imap_port,
                email_addr,
                password,
                force_new=(attempt > 0),
            )
            started_select = time.perf_counter()
            selected_total: Optional[int] = None
            if requested.upper() == "INBOX":
                resolved = _resolve_folder(conn, requested)
            else:
                resolved = _resolve_folder_strict(conn, requested)
                if not resolved:
                    _imap_debug_log(f"get_messages folder request={requested!r} resolved=None email={email_addr}")
                    return []
            select_status, select_data = conn.select(f'"{resolved}"')
            if select_status != "OK":
                _imap_debug_log(f"get_messages select-failed folder={resolved!r} status={select_status}")
                return []
            try:
                selected_total = int((select_data[0] or b"0").decode(errors="replace")) if select_data and select_data[0] else 0
            except Exception:
                selected_total = None
            _imap_debug_log(f"get_messages folder request={requested!r} resolved={resolved!r} email={email_addr}")
            _imap_timing_log("select_folder", started_select, f"folder={resolved}")
            messages: List[Dict] = []
            started_headers = time.perf_counter()
            header_items = _fetch_recent_headers_by_sequence(conn, top, total=selected_total)
            if not header_items:
                ids = _uid_recent_ids(conn, top)
                header_items = []
                for uid in ids:
                    try:
                        _, msg_data = _uid_fetch(
                            conn,
                            uid.decode(),
                            "(FLAGS BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE CONTENT-TYPE)])",
                        )
                        if not msg_data or not msg_data[0] or not isinstance(msg_data[0], tuple):
                            continue
                        meta_raw = msg_data[0][0]
                        meta = meta_raw.decode("utf-8", errors="replace") if isinstance(meta_raw, bytes) else str(meta_raw)
                        header_items.append({"uid": uid.decode(), "raw": msg_data[0][1], "meta": meta})
                    except Exception as e:
                        print(f"[IMAP] Errore fetch uid {uid}: {e}")
                        continue
            _imap_timing_log("fetch_recent_headers", started_headers, f"count={len(header_items)} folder={resolved}")

            for item in header_items:
                try:
                    uid = str(item.get("uid") or "").strip()
                    raw = item.get("raw") or b""
                    meta = str(item.get("meta") or "")
                    msg = email.message_from_bytes(raw)
                    ct = msg.get("Content-Type", "")
                    has_att = "multipart" in ct.lower()
                    is_read = "\\Seen" in meta or "\\SEEN" in meta.upper()
                    from_raw = _hdr_str(msg.get("From", ""))
                    name_part = from_raw.split("<")[0].strip()
                    addr_part = from_raw.split("<")[-1].strip(">") if "<" in from_raw else from_raw.strip()
                    messages.append(
                        {
                            "id": uid,
                            "subject": _decode_header(msg.get("Subject", "")),
                            "from": {
                                "emailAddress": {
                                    "name": _decode_header(name_part),
                                    "address": addr_part,
                                }
                            },
                            "receivedDateTime": msg.get("Date", ""),
                            "isRead": is_read,
                            "bodyPreview": "",
                            "hasAttachments": has_att,
                            "folder": resolved,
                        }
                    )
                except Exception as e:
                    print(f"[IMAP] Errore parse uid {item.get('uid')}: {e}")
                    continue
            def _sort_key(message: Dict) -> float:
                raw_date = message.get("receivedDateTime", "")
                try:
                    return parsedate_to_datetime(raw_date).timestamp()
                except Exception:
                    return 0.0
            messages.sort(key=_sort_key, reverse=True)
            messages = messages[:top]
            _imap_timing_log("get_messages_total", started_total, f"count={len(messages)} folder={resolved}")
            return messages
        except imaplib.IMAP4.abort as e:
            bad_conn = True
            _imap_debug_log(f"get_messages abort attempt={attempt + 1} folder={requested!r} error={e}")
            if attempt == 0:
                continue
            raise
        except Exception:
            bad_conn = True
            raise
        finally:
            if conn_key and conn:
                _release_connection(conn_key, conn, mark_bad=bad_conn)
def get_message(
    imap_host: str,
    imap_port: int,
    email_addr: str,
    password: str,
    message_id: str,
    folder: str = "INBOX",
) -> Dict:
    clean_id = "".join(c for c in str(message_id) if c.isdigit())
    if not clean_id:
        raise ValueError(f"message_id non valido per IMAP: '{message_id}'")

    for attempt in range(2):
        conn = None
        try:
            # Per read/TTS preferiamo una connessione fresca: il riuso della cache
            # su alcuni provider IMAP lascia socket apparentemente vivi ma già chiusi.
            conn = _connect(imap_host, imap_port, email_addr, password)
            requested = (folder or "").strip()
            msg_data = None
            resolved = None

            if requested:
                if requested.upper() == "INBOX":
                    resolved = _resolve_folder(conn, requested)
                elif requested.upper().startswith("INBOX."):
                    # Sottocartelle INBOX.* (es. INBOX.SPAM): prova prima strict,
                    # se non trovata usa resolve con fuzzy match
                    resolved = _resolve_folder_strict(conn, requested) or _resolve_folder(conn, requested)
                else:
                    resolved = _resolve_folder_strict(conn, requested)
                if not resolved:
                    raise ValueError(f"Cartella IMAP non trovata: '{folder}'")
                select_status, _ = conn.select(f'"{resolved}"')
                if select_status != "OK":
                    raise imaplib.IMAP4.abort(f"select failed for folder {resolved!r}: {select_status}")
                _, msg_data = _uid_fetch(conn, clean_id, "(RFC822)")
            else:
                all_folders = _list_folders(conn)
                for rf in all_folders:
                    try:
                        status, _ = conn.select(f'"{rf}"')
                        if status != "OK":
                            continue
                        _, md = _uid_fetch(conn, clean_id, "(RFC822)")
                        if md and md[0] is not None:
                            msg_data = md
                            resolved = rf
                            break
                    except Exception:
                        continue

            if not msg_data or msg_data[0] is None:
                raise ValueError(f"Messaggio IMAP non trovato per id: '{message_id}'")
            raw = msg_data[0][1]
            msg = email.message_from_bytes(raw)
            body, body_type = _get_body(msg)
            attachments = []
            if msg.is_multipart():
                for part in msg.walk():
                    if part.is_multipart():
                        continue
                    cd = str(part.get("Content-Disposition", "")).lower()
                    ct = part.get_content_type()
                    fname = part.get_filename()
                    # Allegato se: Content-Disposition attachment, OPPURE ha un filename/name
                    # (molti client mettono solo il name nel Content-Type), OPPURE inline non-immagine-testo.
                    is_attachment = (
                        "attachment" in cd
                        or bool(fname)
                        or ("inline" in cd and not ct.startswith(("text/", "image/")))
                    )
                    # escludi le parti che sono il corpo testuale vero
                    if ct in ("text/plain", "text/html") and not fname and "attachment" not in cd:
                        is_attachment = False
                    if is_attachment:
                        filename = _decode_header(fname or "allegato")
                        payload = part.get_payload(decode=True) or b""
                        # salta immagini inline minuscole (loghi/tracker < 3KB) senza nome
                        if not fname and ct.startswith("image/") and len(payload) < 3000:
                            continue
                        attachments.append(
                            {
                                "name": filename,
                                "size": len(payload),
                                "type": ct,
                            }
                        )
            from_raw = _hdr_str(msg.get("From", ""))
            name = _decode_header(from_raw.split("<")[0].strip())
            addr = from_raw.split("<")[-1].strip(">") if "<" in from_raw else from_raw.strip()
            if body_type == "html":
                import re as _re
                plain_preview = _re.sub(r"<[^>]+>", " ", body)
                plain_preview = _re.sub(r"\s+", " ", plain_preview).strip()[:4000]
            else:
                plain_preview = body[:4000]
            def _parse_addr_list(header_val: str) -> list:
                result = []
                for part in (header_val or "").split(","):
                    part = part.strip()
                    if not part:
                        continue
                    if "<" in part:
                        n = _decode_header(part.split("<")[0].strip())
                        a = part.split("<")[-1].strip(">").strip()
                    else:
                        n = ""
                        a = _decode_header(part)
                    result.append({"emailAddress": {"name": n, "address": a}})
                return result

            return {
                "id": message_id,
                "subject": _decode_header(msg.get("Subject", "")),
                "from": {"emailAddress": {"name": name, "address": addr}},
                "receivedDateTime": msg.get("Date", ""),
                "body": {"contentType": body_type, "content": body},
                "body_text": plain_preview,
                "attachments": attachments,
                "hasAttachments": len(attachments) > 0,
                "toRecipients": _parse_addr_list(_decode_header(msg.get("To", ""))),
                "ccRecipients": _parse_addr_list(_decode_header(msg.get("Cc", ""))),
            }
        except imaplib.IMAP4.abort as e:
            _imap_debug_log(f"get_message abort attempt={attempt + 1} id={message_id!r} error={e}")
            if attempt == 0:
                continue
            raise
        except Exception:
            raise
        finally:
            _close_conn_safely(conn)


def get_message_headers(
    imap_host: str,
    imap_port: int,
    email_addr: str,
    password: str,
    message_id: str,
    folder: str = "INBOX",
) -> Optional[Dict[str, List[str]]]:
    """Intestazioni complete di un messaggio: {nome-minuscolo: [valori]}.

    Servono alle barriere anti-spam delle regole di risposta (mail_guard):
    Authentication-Results, Auto-Submitted, List-Id, X-Spam-Flag... non
    stanno nel dict di get_message e non devono starci (sono rumore per
    l'agente). BODY.PEEK[HEADER]: il fetch NON marca la mail come letta.
    None = header non recuperabili (il chiamante tratta fail-closed)."""
    clean_id = "".join(c for c in str(message_id) if c.isdigit())
    if not clean_id:
        return None
    conn = None
    try:
        conn = _connect(imap_host, imap_port, email_addr, password)
        requested = (folder or "INBOX").strip()
        if requested.upper() == "INBOX":
            resolved = _resolve_folder(conn, requested)
        else:
            resolved = _resolve_folder_strict(conn, requested) or _resolve_folder(conn, requested)
        if not resolved:
            return None
        status, _ = conn.select(f'"{resolved}"')
        if status != "OK":
            return None
        _, data = _uid_fetch(conn, clean_id, "(BODY.PEEK[HEADER])")
        if not data or data[0] is None:
            return None
        msg = email.message_from_bytes(data[0][1])
        headers: Dict[str, List[str]] = {}
        for name, value in msg.items():
            headers.setdefault(name.lower(), []).append(_hdr_str(value))
        return headers
    except Exception as e:
        _imap_debug_log(f"get_message_headers error id={message_id!r}: {e}")
        return None
    finally:
        _close_conn_safely(conn)


def set_read_status(
    imap_host: str,
    imap_port: int,
    email_addr: str,
    password: str,
    message_id: str,
    folder: str = "INBOX",
    is_read: bool = True,
) -> bool:
    """Marca una mail come letta o non letta."""
    clean_id = "".join(c for c in str(message_id) if c.isdigit())
    if not clean_id:
        return False
    conn = None
    try:
        conn = _connect(imap_host, imap_port, email_addr, password)
        resolved = _resolve_folder(conn, folder) if folder.upper() == "INBOX" else _resolve_folder_strict(conn, folder) or _resolve_folder(conn, folder)
        if not resolved:
            return False
        conn.select(f'"{resolved}"')
        flag = "\\Seen"
        if is_read:
            conn.uid("store", clean_id, "+FLAGS", flag)
        else:
            conn.uid("store", clean_id, "-FLAGS", flag)
        return True
    except Exception as e:
        print(f"[IMAP set_read_status] error: {e}")
        return False
    finally:
        _close_conn_safely(conn)
def send_message(
    smtp_host: str,
    smtp_port: int,
    email_addr: str,
    password: str,
    to: str,
    subject: str,
    body: str,
    cc: Optional[List[str]] = None,
    bcc: Optional[List[str]] = None,
    attachments: Optional[List[Dict]] = None,
    imap_host: Optional[str] = None,
    imap_port: Optional[int] = None,
    imap_password: Optional[str] = None,
    insecure_tls: bool = False,
    extra_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, object]:
    """Invia via SMTP. Ritorna il risultato normalizzato piu' `provider_result`:
    cio' che il server ha DETTO di aver accettato, per destinatario — non
    cio' che abbiamo chiesto. smtplib.sendmail restituisce i RCPT rifiutati
    (vuoto = tutti accettati); lo propaghiamo invece di buttarlo, cosi'
    l'audit non afferma un conteggio mai stato vero (r/mcp, ranbuman).

    "accepted" = accettato al RCPT, al momento dell'invio. NON "consegnato":
    un destinatario accettato e bounce-ato venti minuti dopo non compare
    qui. Il nome del campo dice esattamente questo, di proposito.

    TLS: il certificato del server SMTP e' verificato di default. Per server
    con certificato self-signed l'account puo' dichiarare insecure_tls=True
    (opt-in esplicito, per quell'account soltanto)."""
    import base64
    from email.mime.base import MIMEBase
    from email import encoders
    from email.utils import formatdate
    msg = MIMEMultipart()
    msg["From"] = email_addr
    msg["To"] = to
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    # Le risposte generate dalle regole (0.2) escono marcate RFC 3834:
    # un altro autoresponder che ci rispetta non ci risponde, niente loop.
    for hk, hv in (extra_headers or {}).items():
        msg[hk] = hv
    if cc:
        msg["Cc"] = ", ".join(cc)
    if bcc:
        msg["Bcc"] = ", ".join(bcc)
    msg.attach(MIMEText(body, "plain", "utf-8"))
    # La busta vuole indirizzi, uno per RCPT: "a@x.it, b@y.it" passata
    # intera diventa UN destinatario malformato e meta' della gente non
    # riceve niente, con l'invio che torna success.
    all_recipients = (split_addresses(to) + split_addresses(cc)
                      + split_addresses(bcc))
    for att in attachments or []:
        try:
            data = base64.b64decode(att["data_b64"])
            main_type, sub_type = (att.get("type", "application/octet-stream").split("/", 1))
            part = MIMEBase(main_type, sub_type)
            part.set_payload(data)
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", f'attachment; filename="{att["name"]}"')
            msg.attach(part)
        except Exception as e:
            print(f'[IMAP] Allegato errore {att.get("name")}: {e}')
    try:
        ctx = ssl.create_default_context()
        if insecure_tls:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        if smtp_port == 465:
            with smtplib.SMTP_SSL(smtp_host, smtp_port, context=ctx) as server:
                server.login(email_addr, password)
                refused = server.sendmail(email_addr, all_recipients, msg.as_string())
        else:
            with smtplib.SMTP(smtp_host, smtp_port) as server:
                server.starttls(context=ctx)
                server.login(email_addr, password)
                refused = server.sendmail(email_addr, all_recipients, msg.as_string())
        # sendmail: {} = tutti accettati; altrimenti {rcpt: (code, msg)} per i rifiutati
        refused = refused or {}
        accepted = [r for r in all_recipients if r not in refused]
        provider_result = {
            "provider": "smtp",
            "requested": len(all_recipients),
            "accepted": len(accepted),
            "accepted_recipients": accepted,
            "refused": {k: {"code": v[0], "message": (v[1].decode(errors="replace")
                                                       if isinstance(v[1], bytes) else str(v[1]))}
                        for k, v in refused.items()},
            "tls_verified": not insecure_tls,
        }

        saved = None
        if imap_host and imap_port and imap_password:
            saved = _append_to_sent_folder(
                imap_host,
                imap_port,
                email_addr,
                imap_password,
                msg.as_bytes(),
            )
            if not saved:
                _imap_debug_log("send_message append-sent did-not-save-copy")
        warning = None if (saved is None or saved) else "Mail inviata ma copia non salvata in Inviate"
        if refused:
            warning = (warning + "; " if warning else "") + \
                f"{len(refused)} destinatario/i rifiutato/i dal server: {', '.join(refused)}"
        return {
            "success": bool(accepted),
            "provider": "imap",
            "sent_copy_saved": True if saved is None else bool(saved),
            "warning": warning,
            "provider_result": provider_result,
        }
    except Exception as e:
        print(f"[IMAP] Send error: {e}")
        return {
            "success": False,
            "provider": "imap",
            "sent_copy_saved": False,
            "warning": None,
            "error": str(e),
            "provider_result": {"provider": "smtp", "requested": len(all_recipients),
                                "accepted": 0, "error": str(e),
                                "tls_verified": not insecure_tls},
        }
def delete_message(
    imap_host: str,
    imap_port: int,
    email_addr: str,
    password: str,
    message_id: str,
    folder: Optional[str] = None,
) -> bool:
    """Sposta il messaggio nel Trash IMAP (flag \\Deleted + expunge)."""
    conn_key, conn = _acquire_connection(imap_host, imap_port, email_addr, password)
    bad_conn = False
    try:
        clean_id = "".join(c for c in str(message_id) if c.isdigit())
        if not clean_id:
            return False
        all_folders = _list_folders(conn)
        source_folder: Optional[str] = None
        if folder:
            resolved = _resolve_folder(conn, folder)
            _, md = _uid_fetch(conn, clean_id, "(RFC822.HEADER)")
            if md and md[0] is not None:
                source_folder = resolved
        if not source_folder:
            priority = ["INBOX"] + [rf for rf in all_folders if rf != "INBOX"]
            for rf in priority:
                try:
                    status, _ = conn.select(f'"{rf}"')
                    if status != "OK":
                        continue
                    _, md = _uid_fetch(conn, clean_id, "(RFC822.HEADER)")
                    if md and md[0] is not None and md[0] != b"":
                        source_folder = rf
                        break
                except Exception:
                    continue
        if not source_folder:
            return False
        trash_name: Optional[str] = None
        for candidate in _FOLDER_ALIASES.get("trash", []):
            if candidate in all_folders:
                trash_name = candidate
                break
        if not trash_name:
            for rf in all_folders:
                rf_low = rf.lower()
                if "trash" in rf_low or "deleted" in rf_low or "cestino" in rf_low:
                    trash_name = rf
                    break
        conn.select(f'"{source_folder}"')
        try:
            if trash_name and trash_name != source_folder:
                conn.uid("copy", clean_id, f'"{trash_name}"')
            conn.uid("store", clean_id, "+FLAGS", "\\Deleted")
            conn.expunge()
        except Exception as e:
            print(f"[IMAP] delete_message error: {e}")
            bad_conn = True
            return False
        return True
    finally:
        _release_connection(conn_key, conn, mark_bad=bad_conn)
def get_attachment(
    imap_host: str,
    imap_port: int,
    email_addr: str,
    password: str,
    message_id: str,
    filename: str,
    folder: str = "INBOX",
) -> Tuple[bytes, str]:
    conn_key, conn = _acquire_connection(imap_host, imap_port, email_addr, password)
    bad_conn = False
    try:
        clean_id = "".join(c for c in str(message_id) if c.isdigit())
        if not clean_id:
            raise ValueError(f"message_id non valido per IMAP: '{message_id}'")
        requested = (folder or "INBOX").strip()
        if requested.upper() == "INBOX":
            resolved = _resolve_folder(conn, requested)
        else:
            resolved = _resolve_folder_strict(conn, requested)
        if not resolved:
            raise ValueError(f"Cartella IMAP non trovata: '{folder}'")
        select_status, _ = conn.select(f'"{resolved}"')
        if select_status != "OK":
            raise ValueError(f"Impossibile aprire la cartella IMAP: '{resolved}'")
        _, msg_data = _uid_fetch(conn, clean_id, "(RFC822)")
        if not msg_data or msg_data[0] is None:
            raise ValueError(f"Messaggio IMAP non trovato per id: '{message_id}'")
        raw = msg_data[0][1]
        msg = email.message_from_bytes(raw)
        for part in msg.walk():
            fn = part.get_filename()
            if fn and _decode_header(fn) == filename:
                data = part.get_payload(decode=True) or b""
                return data, part.get_content_type()
        raise ValueError(f'Allegato "{filename}" non trovato nella mail {message_id}')
    except Exception:
        bad_conn = True
        raise
    finally:
        _release_connection(conn_key, conn, mark_bad=bad_conn)

def _safe_text(value: str) -> str:
    return (value or "").lower().strip()


def _matches_query_local(msg, query: str) -> bool:
    q = _safe_text(query)
    if not q:
        return False

    subject = _safe_text(_decode_header(msg.get("Subject", "")))
    from_raw = _safe_text(_decode_header(msg.get("From", "")))
    to_raw = _safe_text(_decode_header(msg.get("To", "")))

    if q in subject or q in from_raw or q in to_raw:
        return True

    try:
        body, _ = _get_body(msg)
        body_text = re.sub(r"<[^>]+>", " ", body or "")
        body_text = re.sub(r"\s+", " ", body_text).lower()
        return q in body_text
    except Exception:
        return False


def _uid_search_safe(conn: imaplib.IMAP4_SSL, field: str, query: str) -> List[bytes]:
    q = str(query or "").strip()
    if not q:
        return []

    attempts = [
        ("UTF-8", field, f'"{q}"'),
        (None, field, f'"{q}"'),
    ]

    for charset, key, value in attempts:
        try:
            typ, data = conn.uid("search", charset, key, value)
            if typ == "OK" and data and data[0]:
                return data[0].split()
        except Exception:
            continue

    return []


def search_messages(
    imap_host: str,
    imap_port: int,
    email_addr: str,
    password: str,
    query: str,
    top: int = 20,
) -> List[Dict]:
    conn_key, conn = _acquire_connection(imap_host, imap_port, email_addr, password)
    bad_conn = False

    try:
        q = str(query or "").strip()
        if not q:
            return []

        try:
            all_folders = _list_folders(conn)
        except Exception:
            all_folders = ["INBOX"]

        folders_to_search = []

        for folder in all_folders or ["INBOX"]:
            fl_clean = (folder or "").lower().replace(".", "").replace("/", "").replace(" ", "").strip()

            if fl_clean in {"drafts", "outbox"}:
                continue

            folders_to_search.append(folder)

        if not folders_to_search:
            folders_to_search = ["INBOX"]

        results: List[Dict] = []
        seen: set = set()

        for folder in folders_to_search:
            try:
                status, select_data = conn.select(f'"{folder}"')
                if status != "OK":
                    continue
            except Exception:
                continue

            ids_subject = _uid_search_safe(conn, "SUBJECT", q)
            ids_from = _uid_search_safe(conn, "FROM", q)
            ids_to = _uid_search_safe(conn, "TO", q)
            ids_text = _uid_search_safe(conn, "TEXT", q) if len(q) >= 4 else []

            folder_ids = list(set(ids_subject) | set(ids_from) | set(ids_to) | set(ids_text))

            if len(folder_ids) < top:
                try:
                    total = int((select_data[0] or b"0").decode(errors="replace")) if select_data and select_data[0] else 0
                except Exception:
                    total = 0

                if total > 0:
                    window = min(total, int(os.environ.get("ADE_MAIL_SEARCH_WINDOW", "3000")))
                    start = max(1, total - window + 1)

                    try:
                        typ, data = conn.fetch(f"{start}:{total}", "(UID RFC822)")
                        if typ == "OK" and data:
                            for part in data:
                                if not isinstance(part, tuple) or len(part) < 2:
                                    continue

                                meta_raw, raw = part
                                meta = meta_raw.decode("utf-8", errors="replace") if isinstance(meta_raw, bytes) else str(meta_raw)
                                uid_match = re.search(r"UID\s+(\d+)", meta, re.IGNORECASE)

                                if not uid_match:
                                    continue

                                msg = email.message_from_bytes(raw)

                                if _matches_query_local(msg, q):
                                    folder_ids.append(uid_match.group(1).encode())
                    except Exception:
                        pass

            for uid in folder_ids:
                if len(results) >= top * 3:
                    break

                uid_str = uid.decode() if isinstance(uid, bytes) else str(uid)
                key = f"{folder}:{uid_str}"

                if key in seen:
                    continue

                seen.add(key)

                try:
                    _, msg_data = _uid_fetch(conn, uid_str, "(RFC822)")
                    if not msg_data or not msg_data[0] or not isinstance(msg_data[0], tuple):
                        continue

                    raw = msg_data[0][1]
                    msg = email.message_from_bytes(raw)

                    if not _matches_query_local(msg, q):
                        continue

                    from_raw = _hdr_str(msg.get("From", ""))
                    name = _decode_header(from_raw.split("<")[0].strip())
                    addr = (
                        from_raw.split("<")[1].rstrip(">").strip()
                        if "<" in from_raw
                        else from_raw.strip()
                    )

                    body, body_type = _get_body(msg)

                    if body_type == "html":
                        preview = re.sub(r"<[^>]+>", " ", body)
                        preview = re.sub(r"\s+", " ", preview).strip()[:500]
                    else:
                        preview = (body or "")[:500]

                    results.append({
                        "id": uid_str,
                        "subject": _decode_header(msg.get("Subject", "")),
                        "from": {"emailAddress": {"name": name, "address": addr}},
                        "receivedDateTime": msg.get("Date", ""),
                        "bodyPreview": preview,
                        "folder": folder,
                    })

                except Exception:
                    continue

        def _sort_key(message: Dict) -> float:
            try:
                return parsedate_to_datetime(message.get("receivedDateTime", "")).timestamp()
            except Exception:
                return 0.0

        results.sort(key=_sort_key, reverse=True)
        return results[:top]

    except Exception:
        bad_conn = True
        raise

    finally:
        _release_connection(conn_key, conn, mark_bad=bad_conn)

def move_to_folder(
    imap_host: str,
    imap_port: int,
    email_addr: str,
    password: str,
    message_id: str,
    folder: str = "",
    source_folder: Optional[str] = None,
) -> bool:
    """
    Sposta un messaggio IMAP in un'altra cartella (es. Spam/Junk, Trash, Sent).
    Strategia:
    - normalizza il nome cartella richiesto (folder_id stile Graph → alias locale)
    - risolve il folder di destinazione con _resolve_folder
    - cerca il messaggio tra le cartelle (INBOX prima, poi le altre)
    - fa COPY nel folder di destinazione
    - marca come \\Deleted nel folder sorgente ed esegue EXPUNGE
    """
    conn_key, conn = _acquire_connection(imap_host, imap_port, email_addr, password)
    bad_conn = False
    try:
        clean_id = "".join(c for c in str(message_id) if c.isdigit())
        if not clean_id:
            _imap_debug_log(f"move_to_folder invalid-id raw={message_id!r}")
            return False
        try:
            all_folders = _list_folders(conn)
        except Exception:
            all_folders = []
        # Normalizza destinazione stile Graph → alias IMAP
        key = (folder or "").strip().lower() or "junk"
        if key in ("deleteditems", "trash", "cestino"):
            key = "trash"
        elif key in ("junkemail", "spam", "postaindesiderata", "posta_indesiderata"):
            key = "junk"
        elif key in ("sentitems", "sent", "postainviata", "posta_inviata"):
            key = "sent"
        elif key in ("inbox",):
            key = "INBOX"
        # Per INBOX non serve resolve — è sempre "INBOX" su qualsiasi server IMAP
        if key == "INBOX":
            dest_folder = "INBOX"
        else:
            dest_folder = _resolve_folder_strict(conn, key) or _resolve_folder(conn, key)
        print(
            f"[IMAP MOVE] start email={email_addr} uid={clean_id} folder_arg={folder!r} "
            f"source_hint={source_folder!r} normalized_key={key!r} dest={dest_folder!r}"
        )
        if not dest_folder:
            print(f"[IMAP MOVE] ABORT dest-folder-not-found key={key!r} all_folders={all_folders}")
            return False
        # Trova la cartella sorgente dove esiste il messaggio
        source_folder_resolved: Optional[str] = None
        if source_folder:
            try:
                # Usa _resolve_folder (con fallback fuzzy) per supportare INBOX.SPAM e simili
                sf_key = source_folder.strip()
                candidate_source = _resolve_folder_strict(conn, sf_key)
                if not candidate_source:
                    candidate_source = _resolve_folder(conn, sf_key)
                if candidate_source:
                    status, _ = conn.select(f'"{candidate_source}"')
                    if status == "OK":
                        if _uid_exists_in_selected_folder(conn, clean_id):
                            source_folder_resolved = candidate_source
                            print(f"[IMAP MOVE] source-from-hint={candidate_source!r}")
            except Exception:
                source_folder_resolved = None
        priority = ["INBOX"] + [rf for rf in all_folders if rf != "INBOX"]
        if not source_folder_resolved:
            for rf in priority:
                try:
                    status, _ = conn.select(f'"{rf}"')
                    if status != "OK":
                        continue
                    if _uid_exists_in_selected_folder(conn, clean_id):
                        source_folder_resolved = rf
                        _imap_debug_log(f"move_to_folder source-detected={rf!r}")
                        break
                except Exception:
                    continue
        if not source_folder_resolved:
            print(f"[IMAP MOVE] ABORT source-not-found uid={clean_id} all_folders={all_folders}")
            return False
        # Se il messaggio è già nella cartella di destinazione, non fare nulla
        if source_folder_resolved == dest_folder:
            print(f"[IMAP MOVE] no-op already-in-destination src={source_folder_resolved!r} dest={dest_folder!r}")
            return True
        # Seleziona sorgente, copia in destinazione, poi cancella dalla sorgente
        status, _ = conn.select(f'"{source_folder_resolved}"')
        if status != "OK":
            _imap_debug_log(f"move_to_folder abort select-source-failed source={source_folder_resolved!r} status={status}")
            return False
        if _uid_move(conn, clean_id, dest_folder):
            print(f"[IMAP MOVE] SUCCESS via UID MOVE uid={clean_id} {source_folder_resolved!r} -> {dest_folder!r}")
            return True

        copy_res = conn.uid("copy", clean_id, f'"{dest_folder}"')
        _imap_debug_log(f"move_to_folder fallback COPY result={copy_res}")
        if not copy_res or copy_res[0] != "OK":
            print(f"[IMAP MOVE] ABORT copy-failed uid={clean_id} -> {dest_folder!r}")
            return False

        store_res = conn.uid("store", clean_id, "+FLAGS", "(\\Deleted)")
        _imap_debug_log(f"move_to_folder fallback STORE result={store_res}")
        if not store_res or store_res[0] != "OK":
            print(f"[IMAP MOVE] ABORT store-failed uid={clean_id}")
            return False

        conn.expunge()
        still_exists = _uid_exists_in_selected_folder(conn, clean_id)
        _imap_debug_log(f"move_to_folder fallback EXPUNGE still_exists={still_exists}")
        return not still_exists
    finally:
        _release_connection(conn_key, conn, mark_bad=bad_conn)
