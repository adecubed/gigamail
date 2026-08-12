"""
mail_memory.py — Memoria email persistente per ADE Mail.
SQLite locale, zero dipendenze esterne, zero cloud.

Struttura:
- senders: profilo per ogni indirizzo email (chi è, tono, argomenti, storia)
- threads: conversazioni indicizzate con FTS5
- patterns: tipo di mail → risposta ideale
- indexer_state: stato dell'indicizzazione per ripresa

Nessuna dipendenza da Brain. Lite e portabile.
"""

import os
import re
import json
import struct
import sqlite3
import threading
import numpy as np
from datetime import datetime, timezone
from typing import Optional, List, Dict, Tuple
from pathlib import Path

# Path del DB in una cartella scrivibile utente, non nella directory app.
try:
    from data_paths import db_path as _db_path
    _DB_PATH = str(_db_path('.mail_memory.db'))
except Exception:
    _fallback_dir = os.path.join(os.environ.get('APPDATA', os.path.expanduser('~')), 'ADE', 'mail')
    os.makedirs(_fallback_dir, exist_ok=True)
    _DB_PATH = os.path.join(_fallback_dir, '.mail_memory.db')
_LOCK = threading.Lock()

# ── INIT ──────────────────────────────────────────────────────────────────────

def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn

def init_db():
    with _get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS senders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                name TEXT DEFAULT '',
                domain TEXT DEFAULT '',
                first_seen TEXT,
                last_seen TEXT,
                email_count INTEGER DEFAULT 0,
                reply_count INTEGER DEFAULT 0,
                avg_reply_hours REAL DEFAULT 0,
                tone TEXT DEFAULT '',           -- formale/informale/tecnico/commerciale
                topics TEXT DEFAULT '[]',       -- JSON array keyword principali
                notes TEXT DEFAULT '',          -- note sintetiche libere
                updated_at TEXT DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_senders_email ON senders(email);
            CREATE INDEX IF NOT EXISTS idx_senders_domain ON senders(domain);

            CREATE TABLE IF NOT EXISTS threads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id TEXT,
                account_id INTEGER NOT NULL,
                direction TEXT NOT NULL,        -- 'received' | 'sent'
                sender_email TEXT NOT NULL,
                sender_name TEXT DEFAULT '',
                subject TEXT DEFAULT '',
                body_preview TEXT DEFAULT '',   -- prime 500 chars
                body_tokens TEXT DEFAULT '',    -- token significativi per FTS
                sent_at TEXT,
                folder TEXT DEFAULT 'inbox',
                has_reply INTEGER DEFAULT 0,
                reply_body TEXT DEFAULT '',     -- corpo della risposta inviata
                reply_sent_at TEXT,
                indexed_at TEXT DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_threads_sender ON threads(sender_email);
            CREATE INDEX IF NOT EXISTS idx_threads_account ON threads(account_id);
            CREATE INDEX IF NOT EXISTS idx_threads_direction ON threads(direction);

            CREATE VIRTUAL TABLE IF NOT EXISTS threads_fts USING fts5(
                subject, body_tokens, sender_email, sender_name, reply_body,
                content='threads',
                content_rowid='id'
            );

            CREATE TRIGGER IF NOT EXISTS threads_fts_insert
            AFTER INSERT ON threads BEGIN
                INSERT INTO threads_fts(rowid, subject, body_tokens, sender_email, sender_name, reply_body)
                VALUES (new.id, new.subject, new.body_tokens, new.sender_email, new.sender_name, new.reply_body);
            END;

            CREATE TRIGGER IF NOT EXISTS threads_fts_update
            AFTER UPDATE ON threads BEGIN
                UPDATE threads_fts SET
                    subject=new.subject,
                    body_tokens=new.body_tokens,
                    sender_email=new.sender_email,
                    sender_name=new.sender_name,
                    reply_body=new.reply_body
                WHERE rowid=new.id;
            END;

            CREATE TABLE IF NOT EXISTS patterns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                pattern_type TEXT NOT NULL,     -- 'subject_token' | 'body_token' | 'sender_domain'
                pattern_value TEXT NOT NULL,
                typical_reply TEXT DEFAULT '',  -- corpo risposta tipica
                frequency INTEGER DEFAULT 1,
                avg_length INTEGER DEFAULT 0,
                tone TEXT DEFAULT '',
                updated_at TEXT DEFAULT (datetime('now')),
                UNIQUE(account_id, pattern_type, pattern_value)
            );
            CREATE INDEX IF NOT EXISTS idx_patterns_account ON patterns(account_id, pattern_type);

            CREATE TABLE IF NOT EXISTS indexer_state (
                account_id INTEGER PRIMARY KEY,
                last_indexed_sent TEXT,         -- data ultima mail inviata indicizzata
                last_indexed_received TEXT,     -- data ultima mail ricevuta indicizzata
                total_indexed INTEGER DEFAULT 0,
                is_running INTEGER DEFAULT 0,
                last_run TEXT,
                error TEXT DEFAULT ''
            );

            -- Embeddings vettoriali per semantic search
            -- embedding: blob di float32 serializzati (1536 dim OpenAI / 768 dim Ollama)
            CREATE TABLE IF NOT EXISTS embeddings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                thread_id INTEGER NOT NULL,
                account_id INTEGER NOT NULL,
                embedding BLOB NOT NULL,
                dim INTEGER NOT NULL,           -- dimensioni del vettore
                model TEXT DEFAULT 'text-embedding-3-small',
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY(thread_id) REFERENCES threads(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_embeddings_account ON embeddings(account_id);
            CREATE INDEX IF NOT EXISTS idx_embeddings_thread ON embeddings(thread_id);
        """)
        conn.commit()

init_db()


# ── EMBEDDING ENGINE ─────────────────────────────────────────────────────────
#
# Priorità:
# 1. OpenAI text-embedding-3-small (1536 dim, $0.002/1M token — quasi gratis)
# 2. Ollama nomic-embed-text (768 dim, zero costo, locale)
# 3. Fallback: None (semantic search disabilitata, FTS5 usato)

import os as _os

_OPENAI_API_KEY = _os.getenv("OPENAI_API_KEY", "")
_OLLAMA_URL = _os.getenv("OLLAMA_URL", "http://localhost:11434")
_EMBED_MODEL_OPENAI = "text-embedding-3-small"
_EMBED_MODEL_OLLAMA = "nomic-embed-text"
_EMBED_DIM_OPENAI = 1536
_EMBED_DIM_OLLAMA = 768

# Cache embedding engine availability
_embed_backend: Optional[str] = None  # 'openai' | 'ollama' | None


def _detect_embed_backend() -> Optional[str]:
    """Rileva quale backend embeddings è disponibile."""
    global _embed_backend
    if _embed_backend is not None:
        return _embed_backend
    # Test OpenAI
    if _OPENAI_API_KEY:
        try:
            import requests as _req
            r = _req.post(
                "https://api.openai.com/v1/embeddings",
                headers={"Authorization": f"Bearer {_OPENAI_API_KEY}",
                         "Content-Type": "application/json"},
                json={"model": _EMBED_MODEL_OPENAI, "input": "test"},
                timeout=5,
            )
            if r.status_code == 200:
                _embed_backend = "openai"
                print(f"[MAIL MEMORY] Embedding backend: OpenAI {_EMBED_MODEL_OPENAI}")
                return _embed_backend
        except Exception:
            pass
    # Test Ollama
    try:
        import requests as _req
        r = _req.post(
            f"{_OLLAMA_URL}/api/embeddings",
            json={"model": _EMBED_MODEL_OLLAMA, "prompt": "test"},
            timeout=5,
        )
        if r.status_code == 200:
            _embed_backend = "ollama"
            print(f"[MAIL MEMORY] Embedding backend: Ollama {_EMBED_MODEL_OLLAMA}")
            return _embed_backend
    except Exception:
        pass
    _embed_backend = None
    print("[MAIL MEMORY] Embedding backend: nessuno — uso solo FTS5")
    return None


def _get_embedding(text: str) -> Optional[Tuple[bytes, int, str]]:
    """Calcola embedding per un singolo testo."""
    results = _get_embeddings_batch([text])
    return results[0] if results else None


def _get_embeddings_batch(texts: List[str]) -> List[Optional[Tuple[bytes, int, str]]]:
    """
    Calcola embeddings per una lista di testi in UNA sola chiamata HTTP.
    OpenAI supporta fino a 2048 input per request.
    Ritorna lista di (blob, dim, model) — None per testi falliti.
    """
    backend = _detect_embed_backend()
    if not backend:
        return [None] * len(texts)

    # Pulisci e tronca testi
    cleaned = [str(t or "")[:4000].strip() for t in texts]
    # Filtra vuoti ma mantieni indici
    valid_indices = [i for i, t in enumerate(cleaned) if t]
    valid_texts = [cleaned[i] for i in valid_indices]

    if not valid_texts:
        return [None] * len(texts)

    results = [None] * len(texts)

    try:
        import requests as _req

        if backend == "openai":
            # Batch da 100 per sicurezza (limite token totali)
            BATCH = 100
            for batch_start in range(0, len(valid_texts), BATCH):
                batch = valid_texts[batch_start:batch_start + BATCH]
                r = _req.post(
                    "https://api.openai.com/v1/embeddings",
                    headers={"Authorization": f"Bearer {_OPENAI_API_KEY}",
                             "Content-Type": "application/json"},
                    json={"model": _EMBED_MODEL_OPENAI, "input": batch},
                    timeout=60,
                )
                data = r.json()
                for item in data.get("data", []):
                    idx_in_batch = item["index"]
                    idx_original = valid_indices[batch_start + idx_in_batch]
                    vec = item["embedding"]
                    dim = len(vec)
                    blob = struct.pack(f"{dim}f", *vec)
                    results[idx_original] = (blob, dim, _EMBED_MODEL_OPENAI)

        elif backend == "ollama":
            # Ollama non supporta batch — chiamate parallele con thread pool
            import concurrent.futures
            def _embed_one(args):
                i, text = args
                try:
                    r = _req.post(
                        f"{_OLLAMA_URL}/api/embeddings",
                        json={"model": _EMBED_MODEL_OLLAMA, "prompt": text},
                        timeout=30,
                    )
                    vec = r.json()["embedding"]
                    dim = len(vec)
                    blob = struct.pack(f"{dim}f", *vec)
                    return i, (blob, dim, _EMBED_MODEL_OLLAMA)
                except Exception:
                    return i, None
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
                for i, result in ex.map(_embed_one, [(valid_indices[j], t) for j, t in enumerate(valid_texts)]):
                    results[i] = result

    except Exception as e:
        print(f"[MAIL MEMORY] embedding batch error: {e}")

    return results


def _blob_to_vec(blob: bytes, dim: int) -> Optional[object]:
    """Deserializza blob bytes in array numpy."""
    try:
        vec = struct.unpack(f"{dim}f", blob)
        return np.array(vec, dtype=np.float32)
    except Exception:
        return None


def _cosine_similarity(a: object, b: object) -> float:
    """Cosine similarity tra due vettori numpy."""
    try:
        dot = np.dot(a, b)
        norm = np.linalg.norm(a) * np.linalg.norm(b)
        return float(dot / norm) if norm > 0 else 0.0
    except Exception:
        return 0.0


def store_embedding(thread_id: int, account_id: int, text: str) -> bool:
    """Calcola e salva embedding per un thread. Ritorna True se salvato."""
    result = _get_embedding(text)
    if not result:
        return False
    blob, dim, model = result
    with _LOCK:
        with _get_conn() as conn:
            existing = conn.execute(
                "SELECT id FROM embeddings WHERE thread_id=?", (thread_id,)
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE embeddings SET embedding=?, dim=?, model=? WHERE thread_id=?",
                    (blob, dim, model, thread_id)
                )
            else:
                conn.execute(
                    "INSERT INTO embeddings (thread_id, account_id, embedding, dim, model) "
                    "VALUES (?,?,?,?,?)",
                    (thread_id, account_id, blob, dim, model)
                )
            conn.commit()
    return True


def store_embeddings_batch(items: List[Tuple[int, int, str]]) -> int:
    """
    Calcola e salva embeddings per una lista di (thread_id, account_id, text).
    Una sola chiamata HTTP per tutti. Ritorna numero di embedding salvati.
    """
    if not items:
        return 0
    texts = [text for _, _, text in items]
    results = _get_embeddings_batch(texts)
    saved = 0
    with _LOCK:
        with _get_conn() as conn:
            for (thread_id, account_id, _), result in zip(items, results):
                if not result:
                    continue
                blob, dim, model = result
                existing = conn.execute(
                    "SELECT id FROM embeddings WHERE thread_id=?", (thread_id,)
                ).fetchone()
                if existing:
                    conn.execute(
                        "UPDATE embeddings SET embedding=?, dim=?, model=? WHERE thread_id=?",
                        (blob, dim, model, thread_id)
                    )
                else:
                    conn.execute(
                        "INSERT INTO embeddings (thread_id, account_id, embedding, dim, model) "
                        "VALUES (?,?,?,?,?)",
                        (thread_id, account_id, blob, dim, model)
                    )
                saved += 1
            conn.commit()
    return saved


def semantic_search(
    account_id: int,
    query: str,
    limit: int = 5,
    min_similarity: float = 0.50,
) -> List[Dict]:
    """
    Ricerca semantica nella mailbox.
    Trasforma la query in vettore e trova le mail più simili.
    Ritorna lista di thread ordinati per similarità decrescente.
    """
    backend = _detect_embed_backend()
    if not backend:
        return []

    result = _get_embedding(query)
    if not result:
        return []

    query_blob, dim, model = result
    query_vec = _blob_to_vec(query_blob, dim)
    if query_vec is None:
        return []

    # Carica tutti gli embedding per questo account
    with _get_conn() as conn:
        rows = conn.execute(
            """SELECT e.thread_id, e.embedding, e.dim,
                      t.subject, t.sender_email, t.body_preview,
                      t.reply_body, t.sent_at, t.direction, t.folder
               FROM embeddings e
               JOIN threads t ON e.thread_id = t.id
               WHERE e.account_id=? AND e.dim=?
               ORDER BY t.sent_at DESC""",
            (account_id, dim)
        ).fetchall()

    if not rows:
        return []

    # Calcola similarità per ogni embedding
    scored = []
    for row in rows:
        vec = _blob_to_vec(row["embedding"], row["dim"])
        if vec is None:
            continue
        sim = _cosine_similarity(query_vec, vec)
        if sim >= min_similarity:
            scored.append({
                "thread_id": row["thread_id"],
                "subject": row["subject"],
                "sender_email": row["sender_email"],
                "body_preview": row["body_preview"],
                "reply_body": row["reply_body"],
                "sent_at": row["sent_at"],
                "direction": row["direction"],
                "folder": row["folder"],
                "similarity": round(sim, 3),
                "match_type": "semantic",
            })

    # Ordina per similarità
    scored.sort(key=lambda x: x["similarity"], reverse=True)
    return scored[:limit]


# ── HELPERS ───────────────────────────────────────────────────────────────────

_STOPWORDS = {
    "il","la","lo","le","gli","un","una","per","con","che","del","della","dei",
    "degli","delle","dal","dalla","dai","dalle","sul","sulla","sui","sulle",
    "nel","nella","nei","nelle","and","the","for","you","your","this","that",
    "mail","email","messaggio","risposta","grazie","saluti","cordiali","caro",
    "gentile","spett","re","fw","fwd","sono","siamo","ho","ha","hanno","avere",
    "essere","fare","come","quando","dove","perché","quindi","però","anche",
    "molto","poco","già","ancora","sempre","mai","solo","tutto","tutti","ogni",
}

def _extract_tokens(text: str, min_len: int = 4, max_tokens: int = 30) -> List[str]:
    """Estrae token significativi da un testo."""
    words = re.findall(r"[a-zA-ZàèéìòùÀÈÉÌÒÙ]{" + str(min_len) + r",}", (text or "").lower())
    seen, out = set(), []
    for w in words:
        if w not in _STOPWORDS and w not in seen:
            seen.add(w)
            out.append(w)
        if len(out) >= max_tokens:
            break
    return out

def _clean_html(html: str) -> str:
    text = re.sub(r'<br\s*/?>', '\n', html, flags=re.I)
    text = re.sub(r'</p>', '\n', text, flags=re.I)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'&nbsp;', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def _extract_domain(email: str) -> str:
    email = (email or "").strip().lower()
    return email.split("@", 1)[1] if "@" in email else ""

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

# ── SENDER PROFILE ────────────────────────────────────────────────────────────

def upsert_sender(email: str, name: str = "", direction: str = "received"):
    """Crea o aggiorna il profilo mittente."""
    email = email.strip().lower()
    if not email or "@" not in email:
        return
    domain = _extract_domain(email)
    now = _now_iso()
    with _LOCK:
        with _get_conn() as conn:
            existing = conn.execute(
                "SELECT id, email_count, reply_count FROM senders WHERE email=?",
                (email,)
            ).fetchone()
            if existing:
                if direction == "received":
                    conn.execute(
                        "UPDATE senders SET email_count=email_count+1, last_seen=?, "
                        "name=CASE WHEN name='' THEN ? ELSE name END, updated_at=? WHERE email=?",
                        (now, name or "", now, email)
                    )
                else:
                    conn.execute(
                        "UPDATE senders SET reply_count=reply_count+1, updated_at=? WHERE email=?",
                        (now, email)
                    )
            else:
                conn.execute(
                    "INSERT OR IGNORE INTO senders "
                    "(email, name, domain, first_seen, last_seen, email_count, reply_count) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (email, name or "", domain, now, now,
                     1 if direction == "received" else 0,
                     1 if direction == "sent" else 0)
                )
            conn.commit()

def update_sender_profile(email: str, tone: str = "", topics: List[str] = None, notes: str = ""):
    """Aggiorna il profilo sintetico del mittente."""
    email = email.strip().lower()
    with _LOCK:
        with _get_conn() as conn:
            conn.execute(
                "UPDATE senders SET tone=?, topics=?, notes=?, updated_at=? WHERE email=?",
                (tone, json.dumps(topics or [], ensure_ascii=False), notes, _now_iso(), email)
            )
            conn.commit()

def get_sender_profile(email: str) -> Optional[Dict]:
    """Restituisce il profilo completo di un mittente."""
    email = email.strip().lower()
    with _get_conn() as conn:
        row = conn.execute("SELECT * FROM senders WHERE email=?", (email,)).fetchone()
        if not row:
            return None
        d = dict(row)
        try:
            d["topics"] = json.loads(d.get("topics") or "[]")
        except Exception:
            d["topics"] = []
        return d

def get_sender_by_domain(domain: str, limit: int = 5) -> List[Dict]:
    """Restituisce mittenti noti per dominio."""
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM senders WHERE domain=? ORDER BY email_count DESC LIMIT ?",
            (domain, limit)
        ).fetchall()
        return [dict(r) for r in rows]

# ── THREAD INDEXING ───────────────────────────────────────────────────────────

def index_message(
    account_id: int,
    message_id: str,
    direction: str,         # 'received' | 'sent'
    sender_email: str,
    subject: str,
    body: str,
    sent_at: str = "",
    folder: str = "inbox",
    reply_body: str = "",
    reply_sent_at: str = "",
    sender_name: str = "",
):
    """Indicizza una mail (ricevuta o inviata) nel DB."""
    sender_email = sender_email.strip().lower()
    body_clean = _clean_html(body)
    # Se body è vuoto usa bodyPreview direttamente (IMAP non porta body completo nella lista)
    if not body_clean and hasattr(body, "__len__") and len(str(body)) < 10:
        body_clean = ""
    body_preview = body_clean[:500] if body_clean else ""
    body_tokens = " ".join(_extract_tokens(subject + " " + body_clean))

    # Aggiorna profilo mittente
    upsert_sender(sender_email, name=sender_name, direction=direction)

    with _LOCK:
        with _get_conn() as conn:
            # Evita duplicati per message_id
            if message_id:
                existing = conn.execute(
                    "SELECT id FROM threads WHERE message_id=? AND account_id=?",
                    (message_id, account_id)
                ).fetchone()
                if existing:
                    # Aggiorna solo se arriva la reply
                    if reply_body:
                        conn.execute(
                            "UPDATE threads SET reply_body=?, reply_sent_at=?, has_reply=1 WHERE id=?",
                            (reply_body[:1000], reply_sent_at, existing["id"])
                        )
                        conn.commit()
                    return

            conn.execute(
                """INSERT INTO threads
                (message_id, account_id, direction, sender_email, sender_name, subject,
                 body_preview, body_tokens, sent_at, folder,
                 has_reply, reply_body, reply_sent_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (message_id or "", account_id, direction, sender_email, sender_name, subject or "",
                 body_preview, body_tokens, sent_at or _now_iso(), folder,
                 1 if reply_body else 0, reply_body[:1000] if reply_body else "",
                 reply_sent_at or "")
            )
            conn.commit()

    # Se è una mail inviata, cerca la mail ricevuta corrispondente e collega
    if direction == "sent":
        try:
            # Cerca mail ricevute con oggetto simile (Re: o stesso subject)
            clean_subject = re.sub(r'^(re|r|fwd|fw):\s*', '', (subject or "").lower().strip())
            if clean_subject:
                with _get_conn() as conn:
                    rows = conn.execute(
                        """SELECT id FROM threads
                        WHERE account_id=? AND direction='received'
                        AND (LOWER(subject) LIKE ? OR LOWER(subject) LIKE ?)
                        LIMIT 5""",
                        (account_id, f"%{clean_subject[:60]}%", f"%re: {clean_subject[:55]}%")
                    ).fetchall()
                    if rows:
                        ids = [r["id"] for r in rows]
                        placeholders = ",".join("?" * len(ids))
                        conn.execute(
                            f"UPDATE threads SET has_reply=1, reply_body=? WHERE id IN ({placeholders})",
                            [body_clean[:500]] + ids
                        )
                        conn.commit()
        except Exception:
            pass

    # Aggiorna pattern se è una risposta
    if direction == "sent":
        _update_patterns(account_id, subject, body_clean, body_clean)

def _update_patterns(account_id: int, subject: str, body: str, reply: str):
    """Aggiorna i pattern tipo-mail → risposta."""
    tokens = _extract_tokens(subject + " " + body, min_len=5, max_tokens=10)
    reply_len = len(reply.split())
    tone = "breve" if reply_len < 50 else "medio" if reply_len < 150 else "lungo"
    now = _now_iso()
    with _LOCK:
        with _get_conn() as conn:
            for token in tokens[:5]:  # max 5 token per mail
                existing = conn.execute(
                    "SELECT id, frequency, avg_length FROM patterns "
                    "WHERE account_id=? AND pattern_type='subject_token' AND pattern_value=?",
                    (account_id, token)
                ).fetchone()
                if existing:
                    new_freq = existing["frequency"] + 1
                    new_avg = int((existing["avg_length"] * existing["frequency"] + reply_len) / new_freq)
                    conn.execute(
                        "UPDATE patterns SET frequency=?, avg_length=?, tone=?, "
                        "typical_reply=?, updated_at=? WHERE id=?",
                        (new_freq, new_avg, tone, reply[:500], now, existing["id"])
                    )
                else:
                    conn.execute(
                        "INSERT OR IGNORE INTO patterns "
                        "(account_id, pattern_type, pattern_value, typical_reply, frequency, avg_length, tone) "
                        "VALUES (?,?,?,?,1,?,?)",
                        (account_id, "subject_token", token, reply[:500], reply_len, tone)
                    )
            conn.commit()

# ── RICERCA ───────────────────────────────────────────────────────────────────

def search_similar_threads(
    account_id: int,
    query: str,
    sender_email: str = "",
    limit: int = 5,
    min_score: float = 0.0,
) -> List[Dict]:
    """
    Cerca thread simili alla query usando tre layer in cascata:
    1. Semantic search (embedding cosine similarity) — se disponibile
    2. Mittente esatto
    3. FTS5 keyword matching
    4. Stesso dominio

    Ritorna thread ordinati per rilevanza, preferendo quelli con reply.
    """
    results = []
    seen_ids: set = set()

    # ── Layer 1: Semantic search ──────────────────────────────────────────────
    if _detect_embed_backend():
        try:
            semantic_hits = semantic_search(account_id, query, limit=limit, min_similarity=0.50)
            for hit in semantic_hits:
                tid = hit.get("thread_id")
                if tid and tid not in seen_ids:
                    seen_ids.add(tid)
                    # Recupera thread completo
                    with _get_conn() as conn:
                        row = conn.execute("SELECT * FROM threads WHERE id=?", (tid,)).fetchone()
                        if row:
                            results.append({**dict(row), "score": hit["similarity"],
                                            "match_type": "semantic"})
        except Exception as e:
            print(f"[MAIL MEMORY] semantic search error: {e}")

    # ── Layer 2: Mittente esatto ──────────────────────────────────────────────
    if sender_email and len(results) < limit:
        with _get_conn() as conn:
            rows = conn.execute(
                """SELECT t.*, 1.0 as score FROM threads t
                WHERE t.account_id=? AND t.sender_email=? AND t.has_reply=1
                AND t.id NOT IN ({})
                ORDER BY t.sent_at DESC LIMIT ?""".format(
                    ",".join("?" * len(seen_ids)) if seen_ids else "0"
                ),
                [account_id, sender_email.lower(), *list(seen_ids), limit - len(results)]
            ).fetchall()
            for row in rows:
                if row["id"] not in seen_ids:
                    seen_ids.add(row["id"])
                    results.append({**dict(row), "match_type": "exact_sender"})

    # ── Layer 3: FTS5 keyword ─────────────────────────────────────────────────
    tokens = _extract_tokens(query, min_len=4, max_tokens=8)
    if tokens and len(results) < limit:
        fts_query = " OR ".join(tokens)
        with _get_conn() as conn:
            try:
                rows = conn.execute(
                    """SELECT t.*, threads_fts.rank as score
                    FROM threads_fts
                    JOIN threads t ON threads_fts.rowid = t.id
                    WHERE threads_fts MATCH ? AND t.account_id=? AND t.has_reply=1
                    AND t.id NOT IN ({})
                    ORDER BY threads_fts.rank LIMIT ?""".format(
                        ",".join("?" * len(seen_ids)) if seen_ids else "0"
                    ),
                    [fts_query, account_id, *list(seen_ids), limit - len(results)]
                ).fetchall()
                for row in rows:
                    if row["id"] not in seen_ids:
                        seen_ids.add(row["id"])
                        results.append({**dict(row), "match_type": "fts"})
            except Exception as e:
                print(f"[MAIL MEMORY] FTS error: {e}")

    # ── Layer 4: Stesso dominio ───────────────────────────────────────────────
    if sender_email and len(results) < limit:
        domain = _extract_domain(sender_email)
        if domain:
            with _get_conn() as conn:
                rows = conn.execute(
                    """SELECT t.*, 0.3 as score FROM threads t
                    WHERE t.account_id=? AND t.sender_email LIKE ? AND t.has_reply=1
                    AND t.id NOT IN ({})
                    ORDER BY t.sent_at DESC LIMIT ?""".format(
                        ",".join("?" * len(seen_ids)) if seen_ids else "0"
                    ),
                    [account_id, f"%@{domain}", *list(seen_ids), limit - len(results)]
                ).fetchall()
                for row in rows:
                    if row["id"] not in seen_ids:
                        results.append({**dict(row), "match_type": "domain"})

    return results[:limit]

def get_context_for_reply(
    account_id: int,
    sender_email: str,
    subject: str,
    body: str,
    max_examples: int = 5,
) -> Dict:
    """
    Restituisce contesto completo per generare una bozza intelligente.
    Include: profilo mittente, thread simili con risposte, pattern rilevanti.
    """
    query = subject + " " + body[:500]
    sender_profile = get_sender_profile(sender_email)
    similar = search_similar_threads(account_id, query, sender_email, limit=max_examples)

    # Pattern rilevanti
    tokens = _extract_tokens(subject + " " + body, min_len=5, max_tokens=5)
    patterns = []
    with _get_conn() as conn:
        for token in tokens:
            row = conn.execute(
                "SELECT * FROM patterns WHERE account_id=? AND pattern_type='subject_token' "
                "AND pattern_value=? AND frequency >= 2 ORDER BY frequency DESC LIMIT 1",
                (account_id, token)
            ).fetchone()
            if row:
                patterns.append(dict(row))

    return {
        "sender_profile": sender_profile,
        "similar_threads": similar,
        "patterns": patterns,
        "has_history": bool(sender_profile or similar),
    }

def build_context_prompt(context: Dict) -> str:
    """Costruisce il testo da iniettare nel prompt LLM."""
    lines = []
    profile = context.get("sender_profile")
    if profile:
        lines.append(f"[MITTENTE CONOSCIUTO: {profile['email']}]")
        if profile.get("name"):
            lines.append(f"Nome: {profile['name']}")
        if profile.get("tone"):
            lines.append(f"Tono preferito nelle risposte: {profile['tone']}")
        if profile.get("topics"):
            topics = profile["topics"]
            if isinstance(topics, list) and topics:
                lines.append(f"Argomenti frequenti: {', '.join(topics[:5])}")
        lines.append(f"Mail ricevute: {profile.get('email_count', 0)} | "
                     f"Risposte inviate: {profile.get('reply_count', 0)}")
        if profile.get("notes"):
            lines.append(f"Note: {profile['notes']}")
        lines.append("")

    similar = context.get("similar_threads", [])
    if similar:
        lines.append(f"[RISPOSTE PRECEDENTI A MAIL SIMILI — {len(similar)} esempi]:")
        for i, t in enumerate(similar[:3], 1):
            if t.get("reply_body"):
                lines.append(f"\nEsempio {i} ({t.get('match_type', '')}):")
                lines.append(f"  Oggetto originale: {t.get('subject', '')[:80]}")
                lines.append(f"  Risposta inviata: {t.get('reply_body', '')[:300]}")
        lines.append("")

    patterns = context.get("patterns", [])
    if patterns:
        best = patterns[0]
        lines.append(f"[PATTERN RILEVATO — usato {best['frequency']} volte]:")
        lines.append(f"Risposta tipica per questo tipo di mail: {best.get('typical_reply', '')[:200]}")
        lines.append(f"Lunghezza tipica: {best.get('tone', 'medio')}")

    if not lines:
        return ""

    return "CONTESTO STORICO EMAIL (usa per personalizzare la risposta):\n" + "\n".join(lines)

# ── INDEXER MULTI-AGENTE ─────────────────────────────────────────────────────
#
# Architettura:
# - Coordinator: divide la mailbox in chunk, assegna a N agenti worker
# - Worker pool: 3 thread IMAP paralleli (limite sicuro per tutti i provider)
# - Chunk size: 100 mail per agente per round
# - Zero LLM: solo parsing testo e SQLite — veloce
# - Auto-start: chiamato da server.py dopo addImapAccount / completeLogin
#
# Stima tempi:
#   10.000 mail × 3 agenti = ~15-20 minuti vs ~3 ore con 1 agente

import queue as _queue

NUM_AGENTS = 3          # connessioni IMAP parallele — sicuro su tutti i provider
CHUNK_SIZE = 100        # mail per chunk per agente

# Stato globale indicizzazione (per account)
_indexer_state_cache: Dict[int, Dict] = {}
_indexer_stop_flags: Dict[int, threading.Event] = {}
_indexer_counters: Dict[int, Dict] = {}
_indexer_lock = threading.Lock()


def get_indexer_state(account_id: int) -> Dict:
    """Stato corrente dell'indicizzazione."""
    # Prima controlla cache in memoria (aggiornata in tempo reale)
    with _indexer_lock:
        if account_id in _indexer_state_cache:
            return dict(_indexer_state_cache[account_id])
    # Poi DB
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM indexer_state WHERE account_id=?", (account_id,)
        ).fetchone()
        if not row:
            return {"account_id": account_id, "total_indexed": 0, "is_running": False}
        return dict(row)


def get_stats() -> Dict:
    """Statistiche globali del DB."""
    with _get_conn() as conn:
        senders = conn.execute("SELECT COUNT(*) FROM senders").fetchone()[0]
        threads = conn.execute("SELECT COUNT(*) FROM threads").fetchone()[0]
        with_reply = conn.execute("SELECT COUNT(*) FROM threads WHERE has_reply=1").fetchone()[0]
        patterns = conn.execute("SELECT COUNT(*) FROM patterns").fetchone()[0]
    return {
        "senders": senders,
        "threads": threads,
        "threads_with_reply": with_reply,
        "patterns": patterns,
        "db_path": _DB_PATH,
    }


def delete_account_data(account_id: int) -> Dict:
    """
    Cancella TUTTI i dati indicizzati di un account: threads, embeddings,
    indexer_state, patterns + voci FTS5 collegate.
    Usato quando l'utente elimina un account dall'app.
    Ritorna conteggio righe cancellate per categoria.
    """
    deleted = {"threads": 0, "embeddings": 0, "patterns": 0, "indexer_state": 0, "fts": 0}
    with _get_conn() as conn:
        # Recupera i rowid di threads per account_id (servono per pulire FTS prima del DELETE)
        thread_ids = [r[0] for r in conn.execute(
            "SELECT id FROM threads WHERE account_id=?", (account_id,)
        ).fetchall()]
        # FTS5 non ha trigger DELETE: pulisco manualmente per ogni rowid
        if thread_ids:
            placeholders = ",".join("?" * len(thread_ids))
            cur = conn.execute(
                f"DELETE FROM threads_fts WHERE rowid IN ({placeholders})",
                thread_ids,
            )
            deleted["fts"] = cur.rowcount or 0
        # Embeddings (tabella separata, riferimento per account_id)
        cur = conn.execute("DELETE FROM embeddings WHERE account_id=?", (account_id,))
        deleted["embeddings"] = cur.rowcount or 0
        # Threads
        cur = conn.execute("DELETE FROM threads WHERE account_id=?", (account_id,))
        deleted["threads"] = cur.rowcount or 0
        # Patterns
        cur = conn.execute("DELETE FROM patterns WHERE account_id=?", (account_id,))
        deleted["patterns"] = cur.rowcount or 0
        # Indexer state
        cur = conn.execute("DELETE FROM indexer_state WHERE account_id=?", (account_id,))
        deleted["indexer_state"] = cur.rowcount or 0
        conn.commit()
    # Svuota anche la cache in-memory dello stato indexer per quell'account
    try:
        with _indexer_lock:
            _indexer_state_cache.pop(account_id, None)
            _indexer_counters.pop(account_id, None)
    except Exception:
        pass
    print(f"[MAIL MEMORY] delete_account_data({account_id}): {deleted}")
    return deleted


def run_all_indexers(mail_router, get_all_accounts_fn, num_agents: int = NUM_AGENTS) -> Dict:
    """
    Avvia indicizzazione per TUTTI gli account configurati in sequenza.
    Ogni account viene indicizzato con il suo pool di agenti.
    """
    try:
        accounts = get_all_accounts_fn()
    except Exception as e:
        return {"started": False, "reason": f"Errore lettura account: {e}"}

    if not accounts:
        return {"started": False, "reason": "Nessun account configurato"}

    started = []

    def _run_all():
        for acc in accounts:
            aid = acc.get("id") or acc.get("account_id")
            if not aid:
                continue
            print(f"[MAIL MEMORY] Indicizzazione account {aid} ({acc.get('email', '')})")
            result = run_indexer(aid, mail_router, num_agents)
            if result.get("started"):
                # Aspetta che questo account finisca prima di passare al prossimo
                # Controlla ogni 5 secondi
                import time
                while True:
                    state = get_indexer_state(aid)
                    if not state.get("is_running"):
                        break
                    time.sleep(5)
            print(f"[MAIL MEMORY] Account {aid} completato")
        print("[MAIL MEMORY] Tutti gli account indicizzati")

    import threading as _t
    _t.Thread(target=_run_all, daemon=True, name="mm-all-indexer").start()

    return {
        "started": True,
        "accounts": len(accounts),
        "account_ids": [a.get("id") for a in accounts if a.get("id")],
    }


def run_indexer(account_id: int, mail_router, num_agents: int = NUM_AGENTS) -> Dict:
    """
    Avvia indicizzazione multi-agente in background.
    Ritorna subito — il lavoro gira in thread separati.
    """
    with _indexer_lock:
        # Controlla se già in corso
        if account_id in _indexer_state_cache:
            state = _indexer_state_cache[account_id]
            if state.get("is_running"):
                return {"started": False, "reason": "Indexer già in corso"}

        # Crea stop flag e counter per questo account
        stop_flag = threading.Event()
        _indexer_stop_flags[account_id] = stop_flag
        _indexer_counters[account_id] = {
            "total": 0, "agents_done": 0, "error": ""
        }
        _indexer_state_cache[account_id] = {
            "account_id": account_id,
            "is_running": True,
            "total_indexed": 0,
            "agents_active": 0,
            "last_run": _now_iso(),
            "error": "",
        }

    # Avvia coordinator in thread
    t = threading.Thread(
        target=_coordinator,
        args=(account_id, mail_router, num_agents, stop_flag),
        daemon=True,
        name=f"mm-coordinator-{account_id}",
    )
    t.start()
    print(f"[MAIL MEMORY] Indicizzazione avviata — account {account_id}, {num_agents} agenti")
    return {"started": True, "account_id": account_id, "agents": num_agents}


def stop_indexer(account_id: Optional[int] = None):
    """Ferma l'indicizzazione per un account (o tutti)."""
    with _indexer_lock:
        flags = (
            {account_id: _indexer_stop_flags[account_id]}
            if account_id and account_id in _indexer_stop_flags
            else dict(_indexer_stop_flags)
        )
    for flag in flags.values():
        flag.set()


def _resolve_folders(account_id: int, mail_router) -> List[str]:
    """
    Ritorna tutte le cartelle indicizzabili per questo account.
    Esclude solo trash/spam/junk/drafts/outbox.
    """
    _SKIP = {
        "trash", "deleteditems", "cestino", "deleted",
        "junkemail", "spam", "junk", "postaindesiderata",
        "drafts", "bozze", "draft", "outbox",
    }

    def _should_skip(name: str, display: str, flags: str) -> bool:
        for val in [name.lower(), display.lower(), flags.lower()]:
            clean = val.replace(".", "").replace("/", "").replace(" ", "").replace("_", "")
            if clean in _SKIP:
                return True
            for skip in _SKIP:
                if skip in clean:
                    return True
        return False

    try:
        folders = mail_router.list_folders(account_id)
        result = []
        for f in (folders or []):
            name    = str(f.get("id") or f.get("name") or "").strip()
            display = str(f.get("displayName") or "").strip()
            flags   = str(f.get("flags") or "").lower()
            if not name:
                continue
            if _should_skip(name, display, flags):
                continue
            result.append(name)

        if not result:
            result = ["inbox", "sent"]

        print(f"[MAIL MEMORY] Cartelle da indicizzare: {result}")
        return result

    except Exception as e:
        print(f"[MAIL MEMORY] _resolve_folders error: {e} — uso default")
        return ["inbox", "sent"]


def _count_folder_messages(account_id: int, mail_router, folder: str, timeout_s: int = 20) -> int:
    """
    Conta le mail in una cartella.
    Per IMAP usa get_all_uids (conta reale).
    Per Microsoft usa fetch paginata fino a 1000.
    """
    import time as _time
    try:
        # IMAP: conta tramite UID list — accurata su tutta la mailbox
        if hasattr(mail_router, 'get_all_uids'):
            try:
                uids = mail_router.get_all_uids(account_id, folder)
                if uids is not None:
                    return len(uids)
            except Exception:
                pass

        # Microsoft Graph / fallback: fetch paginata
        import concurrent.futures as _cf
        total = 0
        skip = 0
        PAGE = 100
        with _cf.ThreadPoolExecutor(max_workers=1) as ex:
            while True:
                future = ex.submit(mail_router.get_messages, account_id, folder, PAGE, skip)
                try:
                    msgs = future.result(timeout=timeout_s)
                    count = len(msgs) if msgs else 0
                    total += count
                    if count < PAGE:
                        break
                    skip += PAGE
                    if skip >= 10000:  # cap di sicurezza
                        break
                except _cf.TimeoutError:
                    print(f"[MAIL MEMORY COORDINATOR] timeout conteggio {folder} — stop")
                    break
        return total
    except Exception as e:
        print(f"[MAIL MEMORY COORDINATOR] count error ({folder}): {e}")
        return 0


_FULL_REINDEX = False  # True = re-index completo (ignora dedup UID); False = incrementale


def _existing_message_ids(account_id: int, folder: str) -> set:
    """
    Ritorna i message_id (UID per IMAP) gia indicizzati per questo account+cartella.
    Usato per l'indicizzazione incrementale: si scaricano solo le mail nuove.
    """
    ids = set()
    try:
        with _get_conn() as conn:
            rows = conn.execute(
                "SELECT message_id FROM threads WHERE account_id=? AND folder=? AND message_id != ''",
                (account_id, folder),
            ).fetchall()
        for r in rows:
            mid = r["message_id"] if not isinstance(r, tuple) else r[0]
            if mid:
                ids.add(str(mid))
    except Exception as e:
        print(f"[MAIL MEMORY] _existing_message_ids error ({folder}): {e}")
    return ids


def _coordinator(
    account_id: int,
    mail_router,
    num_agents: int,
    stop_flag: threading.Event,
):
    """
    Coordinator: conta le mail in ogni cartella, crea esattamente i chunk necessari.
    """
    work_queue: _queue.Queue = _queue.Queue()
    folders_to_index = _resolve_folders(account_id, mail_router)
    total_chunks = 0

    for folder in folders_to_index:
        if stop_flag.is_set():
            break
        try:
            # IMAP: usa UID list per chunk precisi
            all_uids = None
            if hasattr(mail_router, 'get_all_uids'):
                try:
                    all_uids = mail_router.get_all_uids(account_id, folder)
                except Exception:
                    all_uids = None

            if all_uids is not None:
                # INCREMENTALE: indicizza solo gli UID non ancora presenti nel DB
                if not _FULL_REINDEX:
                    _known = _existing_message_ids(account_id, folder)
                    if _known:
                        _before = len(all_uids)
                        all_uids = [u for u in all_uids if str(u) not in _known]
                        print(f"[MAIL MEMORY COORDINATOR] {folder}: incrementale "
                              f"{_before} totali, {len(all_uids)} nuove da indicizzare")
                count = len(all_uids)
                if count == 0:
                    print(f"[MAIL MEMORY COORDINATOR] {folder}: nessuna nuova mail, skip")
                    continue
                print(f"[MAIL MEMORY COORDINATOR] {folder}: {count} mail (IMAP UID), "
                      f"{(count + CHUNK_SIZE - 1) // CHUNK_SIZE} chunk")
                for i in range(0, count, CHUNK_SIZE):
                    chunk_uids = all_uids[i:i + CHUNK_SIZE]
                    work_queue.put({"folder": folder, "skip": i, "size": CHUNK_SIZE, "uids": chunk_uids})
                    total_chunks += 1
            else:
                # Microsoft Graph: paginazione per skip
                count = _count_folder_messages(account_id, mail_router, folder)
                if count == 0:
                    print(f"[MAIL MEMORY COORDINATOR] {folder}: vuota, skip")
                    continue
                print(f"[MAIL MEMORY COORDINATOR] {folder}: {count} mail, "
                      f"{(count + CHUNK_SIZE - 1) // CHUNK_SIZE} chunk")
                for skip in range(0, count, CHUNK_SIZE):
                    work_queue.put({"folder": folder, "skip": skip, "size": CHUNK_SIZE})
                    total_chunks += 1
        except Exception as e:
            print(f"[MAIL MEMORY COORDINATOR] folder {folder} error: {e}")

    print(f"[MAIL MEMORY COORDINATOR] totale chunk da processare: {total_chunks}")

    # Aggiungi sentinel per ogni agente (segnala fine lavoro)
    for _ in range(num_agents):
        work_queue.put(None)

    # Aggiorna stato agenti attivi
    with _indexer_lock:
        if account_id in _indexer_state_cache:
            _indexer_state_cache[account_id]["agents_active"] = num_agents

    # Lancia worker pool
    workers = []
    for i in range(num_agents):
        t = threading.Thread(
            target=_worker,
            args=(i, account_id, mail_router, work_queue, stop_flag),
            daemon=True,
            name=f"mm-worker-{account_id}-{i}",
        )
        t.start()
        workers.append(t)

    # Aspetta che tutti i worker finiscano
    for t in workers:
        t.join()

    # Finalizza
    with _indexer_lock:
        counter = _indexer_counters.get(account_id, {})
        total = counter.get("total", 0)
        error = counter.get("error", "")
        if account_id in _indexer_state_cache:
            _indexer_state_cache[account_id].update({
                "is_running": False,
                "total_indexed": total,
                "agents_active": 0,
                "error": error,
            })

    # Persisti su DB
    _persist_indexer_state(account_id, total, error)
    print(f"[MAIL MEMORY] Indicizzazione completata — account {account_id}, {total} mail")


def _worker(
    worker_id: int,
    account_id: int,
    mail_router,
    work_queue: _queue.Queue,
    stop_flag: threading.Event,
):
    """
    Worker: processa chunk dalla queue finché non arriva None.
    Ogni worker ha la propria connessione IMAP indipendente.
    """
    local_count = 0

    while not stop_flag.is_set():
        try:
            chunk = work_queue.get(timeout=5)
        except _queue.Empty:
            continue

        if chunk is None:  # sentinel
            work_queue.task_done()
            break

        folder = chunk["folder"]
        skip = chunk["skip"]
        size = chunk["size"]
        chunk_uids = chunk.get("uids")  # presente solo per IMAP

        try:
            if chunk_uids and hasattr(mail_router, 'fetch_messages_by_uids'):
                messages = mail_router.fetch_messages_by_uids(
                    account_id, uids=chunk_uids, folder=folder
                )
            else:
                messages = mail_router.get_messages(
                    account_id, folder=folder, top=size, skip=skip
                )
            if not messages:
                work_queue.task_done()
                _drain_folder_chunks(work_queue, folder, stop_flag)
                continue

            # Step 1: indicizza tutte le mail nel DB (senza embedding)
            indexed_ids = []  # lista di (thread_id, account_id, embed_text)
            for msg in messages:
                if stop_flag.is_set():
                    break
                try:
                    _index_single_message(account_id, msg, folder)
                    local_count += 1
                    # Recupera thread_id e prepara testo per embedding
                    msg_id = str(msg.get("id") or msg.get("uid") or "")
                    subject = msg.get("subject") or ""
                    body_obj = msg.get("body") or {}
                    body = body_obj.get("content") if isinstance(body_obj, dict) else msg.get("body_text") or msg.get("bodyPreview") or ""
                    body_clean = _clean_html(str(body or ""))
                    embed_text = f"{subject} {body_clean[:800]}".strip()
                    if embed_text and msg_id:
                        indexed_ids.append((msg_id, embed_text))
                except Exception:
                    pass

            # Step 2: batch embeddings per tutto il chunk — UNA sola chiamata HTTP
            if indexed_ids and _detect_embed_backend() and not stop_flag.is_set():
                try:
                    # Recupera thread_ids dal DB
                    batch_items = []
                    with _get_conn() as conn:
                        for msg_id, embed_text in indexed_ids:
                            row = conn.execute(
                                "SELECT id FROM threads WHERE message_id=? AND account_id=?",
                                (msg_id, account_id)
                            ).fetchone()
                            if row:
                                batch_items.append((row["id"], account_id, embed_text))
                    if batch_items:
                        saved = store_embeddings_batch(batch_items)
                        print(f"[MAIL MEMORY WORKER {worker_id}] batch embeddings: {saved}/{len(batch_items)} salvati")
                except Exception as e:
                    print(f"[MAIL MEMORY WORKER {worker_id}] batch embed error: {e}")

            # Aggiorna counter globale
            with _indexer_lock:
                if account_id in _indexer_counters:
                    _indexer_counters[account_id]["total"] += len(messages)
                if account_id in _indexer_state_cache:
                    _indexer_state_cache[account_id]["total_indexed"] = (
                        _indexer_counters[account_id]["total"]
                    )

            if len(messages) < size:
                _drain_folder_chunks(work_queue, folder, stop_flag)

        except Exception as e:
            print(f"[MAIL MEMORY WORKER {worker_id}] chunk error ({folder}@{skip}): {e}")
            with _indexer_lock:
                if account_id in _indexer_counters:
                    _indexer_counters[account_id]["error"] = str(e)

        finally:
            work_queue.task_done()

    print(f"[MAIL MEMORY WORKER {worker_id}] done — {local_count} mail processate")


def _drain_folder_chunks(
    work_queue: _queue.Queue,
    folder: str,
    stop_flag: threading.Event,
):
    """Rimuove dalla queue i chunk rimanenti di una cartella finita."""
    drained = []
    try:
        while True:
            try:
                item = work_queue.get_nowait()
                if item is None or item.get("folder") != folder:
                    drained.append(item)  # rimetti gli altri
                else:
                    work_queue.task_done()
            except _queue.Empty:
                break
    except Exception:
        pass
    for item in drained:
        work_queue.put(item)


def _persist_indexer_state(account_id: int, total: int, error: str):
    """Persiste lo stato finale su SQLite."""
    with _LOCK:
        with _get_conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO indexer_state
                (account_id, is_running, total_indexed, last_run, error)
                VALUES (?,0,?,?,?)""",
                (account_id, total, _now_iso(), error)
            )
            conn.commit()


def _set_indexer_running(account_id: int, running: bool, total: int = 0, error: str = ""):
    """Compatibility shim — non più usato direttamente."""
    _persist_indexer_state(account_id, total, error)


def _index_folder(account_id: int, mail_router, folder: str, batch_size: int) -> int:
    """Compatibility shim per chiamate dirette single-thread."""
    total = 0
    skip = 0
    while True:
        try:
            messages = mail_router.get_messages(account_id, folder=folder, top=batch_size, skip=skip)
        except Exception as e:
            break
        if not messages:
            break
        for msg in messages:
            try:
                _index_single_message(account_id, msg, folder)
                total += 1
            except Exception:
                pass
        if len(messages) < batch_size:
            break
        skip += batch_size
    return total


def _index_single_message(account_id: int, msg: Dict, folder: str):
    """Indicizza un singolo messaggio — thread-safe."""
    msg_id = str(msg.get("id") or msg.get("uid") or "")
    subject = msg.get("subject") or ""
    sent_at = (
        msg.get("receivedDateTime") or msg.get("sentDateTime")
        or msg.get("date") or ""
    )

    from_obj = msg.get("from") or {}
    if isinstance(from_obj, dict):
        addr_obj = from_obj.get("emailAddress") or {}
        sender_email = addr_obj.get("address") or from_obj.get("address") or ""
        sender_name = addr_obj.get("name") or from_obj.get("name") or ""
    else:
        sender_email = str(from_obj)
        sender_name = ""

    # Fallback sender per IMAP: campo "sender" o "from_addr"
    if not sender_email:
        sender_email = str(msg.get("sender") or msg.get("from_addr") or "")

    # Body: prova tutti i campi disponibili
    body_obj = msg.get("body") or {}
    if isinstance(body_obj, dict):
        body = body_obj.get("content") or ""
    else:
        body = str(body_obj) if body_obj else ""
    # Fallback per IMAP — usa body_text, bodyPreview, snippet
    if not body:
        body = (msg.get("body_text") or msg.get("bodyPreview") or
                msg.get("snippet") or msg.get("preview") or "")

    # direction: INBOX.Sent → sent, altrimenti received
    folder_lower = (folder or "").lower()
    direction = "sent" if (
        folder_lower in ("sent", "inbox.sent") or
        "sent" in folder_lower
    ) else "received"

    # Per le INVIATE, sender_email rappresenta il CONTRAENTE (destinatario),
    # non noi stessi: cosi sender_history conta correttamente le inviate
    # e la ricerca per contatto trova anche le nostre risposte.
    if direction == "sent":
        to_list = msg.get("toRecipients") or msg.get("to") or []
        if isinstance(to_list, str):
            to_list = [to_list]
        rec_email, rec_name = "", ""
        if isinstance(to_list, list) and to_list:
            first = to_list[0] or {}
            if isinstance(first, dict):
                a = first.get("emailAddress") or first
                if isinstance(a, dict):
                    rec_email = a.get("address") or ""
                    rec_name = a.get("name") or ""
                else:
                    rec_email = str(a)
            else:
                rec_email = str(first)
        if rec_email:
            sender_email, sender_name = rec_email, rec_name

    index_message(
        account_id=account_id,
        message_id=msg_id,
        direction=direction,
        sender_email=sender_email,
        subject=subject,
        body=body,
        sent_at=sent_at,
        folder=folder,
        sender_name=sender_name,
    )

    # Nota: embedding calcolato in batch dal worker dopo ogni chunk
    # per efficienza (una sola chiamata HTTP per 100 mail)

def fast_search(account_id: int, query: str, limit: int = 50) -> List[Dict]:
    """
    Ricerca VELOCE stile Outlook: solo match testuale diretto sul DB locale.
    Nessun embedding, nessuna chiamata IMAP/Graph live.
    Priorità: match sul mittente (nome/email) > oggetto > corpo.
    """
    q = (query or "").strip()
    if not q or len(q) < 2:
        return []

    results = {}
    like = f"%{q}%"

    with _get_conn() as conn:
        rows = conn.execute(
            """SELECT id, message_id, subject, sender_email, sender_name,
                      body_preview, sent_at, folder, direction, has_reply
               FROM threads
               WHERE account_id=? AND (
                   sender_name LIKE ? OR sender_email LIKE ? OR subject LIKE ?
               )
               ORDER BY sent_at DESC LIMIT ?""",
            (account_id, like, like, like, limit * 2)
        ).fetchall()
        for r in rows:
            d = dict(r)
            blob_sender = ((d.get("sender_name") or "") + " " + (d.get("sender_email") or "")).lower()
            if q.lower() in blob_sender:
                d["_score"] = 3
            elif q.lower() in (d.get("subject") or "").lower():
                d["_score"] = 2
            else:
                d["_score"] = 1
            results[d["id"]] = d

        if len(results) < limit:
            tokens = _extract_tokens(q, min_len=3, max_tokens=8)
            if tokens:
                fts_q = " OR ".join(tokens)
                try:
                    frows = conn.execute(
                        """SELECT t.id, t.message_id, t.subject, t.sender_email, t.sender_name,
                                  t.body_preview, t.sent_at, t.folder, t.direction, t.has_reply
                           FROM threads_fts
                           JOIN threads t ON threads_fts.rowid = t.id
                           WHERE threads_fts MATCH ? AND t.account_id=?
                           ORDER BY threads_fts.rank LIMIT ?""",
                        (fts_q, account_id, limit)
                    ).fetchall()
                    for r in frows:
                        if r["id"] not in results:
                            d = dict(r)
                            d["_score"] = 1
                            results[d["id"]] = d
                except Exception as e:
                    print(f"[FAST SEARCH] fts error: {e}")

    out = list(results.values())
    out.sort(key=lambda x: (x.get("_score", 0), x.get("sent_at") or ""), reverse=True)
    return out[:limit]


# ── STORICO MITTENTE (proattivo: apri mail → vedi storia con quel mittente) ──
def sender_history(account_id: int, sender_email: str, limit: int = 10) -> dict:
    """Ritorna lo storico delle interazioni con un mittente (slegato da Brain, solo DB mail).
    {count, sent_count, received_count, first_date, last_date, recent:[...], temi:[...]}.
    Match per sender_email esatto (case-insensitive)."""
    import re as _re
    out = {
        "sender_email": sender_email,
        "count": 0, "sent_count": 0, "received_count": 0,
        "first_date": "", "last_date": "",
        "recent": [], "temi": [],
    }
    if not sender_email:
        return out
    se = sender_email.strip().lower()
    try:
        with _get_conn() as conn:
            # totali + direzioni
            row = conn.execute(
                """SELECT COUNT(*) c,
                          SUM(CASE WHEN direction='sent' THEN 1 ELSE 0 END) sent_c,
                          SUM(CASE WHEN direction='received' THEN 1 ELSE 0 END) recv_c
                   FROM threads
                   WHERE account_id=? AND LOWER(sender_email)=?""",
                (account_id, se)
            ).fetchone()
            if row:
                out["count"] = row["c"] or 0
                out["sent_count"] = row["sent_c"] or 0
                out["received_count"] = row["recv_c"] or 0
            if out["count"] == 0:
                return out

            # ultime N mail (oggetto, data, direzione)
            recent_rows = conn.execute(
                """SELECT subject, sent_at, direction, id, message_id, folder, sender_name
                   FROM threads
                   WHERE account_id=? AND LOWER(sender_email)=?
                   ORDER BY sent_at DESC LIMIT ?""",
                (account_id, se, limit)
            ).fetchall()
            for r in recent_rows:
                out["recent"].append({
                    "subject": r["subject"] or "(senza oggetto)",
                    "date": r["sent_at"] or "",
                    "direction": r["direction"] or "",
                    "thread_id": r["id"],
                    "message_id": r["message_id"],
                    "folder": r["folder"] or "INBOX",
                })
            if recent_rows:
                out["sender_name"] = recent_rows[0]["sender_name"] or ""

            # date estreme (min/max su tutte)
            drow = conn.execute(
                """SELECT MIN(sent_at) mn, MAX(sent_at) mx
                   FROM threads WHERE account_id=? AND LOWER(sender_email)=?""",
                (account_id, se)
            ).fetchone()
            if drow:
                out["first_date"] = drow["mn"] or ""
                out["last_date"] = drow["mx"] or ""

            # temi ricorrenti: parole frequenti negli oggetti (no stopword, no Re/Fwd)
            subj_rows = conn.execute(
                """SELECT subject FROM threads
                   WHERE account_id=? AND LOWER(sender_email)=? AND subject IS NOT NULL
                   ORDER BY sent_at DESC LIMIT 80""",
                (account_id, se)
            ).fetchall()
            stop = {
                "re", "fwd", "fw", "r", "i", "e", "il", "la", "le", "lo", "gli", "un", "una",
                "di", "da", "del", "della", "per", "con", "che", "the", "to", "of", "for",
                "and", "your", "you", "tua", "tuo", "your", "il", "su", "in", "a", "al",
                "ade", "mail", "email", "messaggio", "ciao", "buongiorno", "salve",
            }
            freq = {}
            for sr in subj_rows:
                subj = (sr["subject"] or "").lower()
                for w in _re.findall(r"[a-zàèéìòù0-9]{4,}", subj):
                    if w in stop:
                        continue
                    freq[w] = freq.get(w, 0) + 1
            temi = sorted(freq.items(), key=lambda x: x[1], reverse=True)
            out["temi"] = [w for w, n in temi[:6] if n >= 2]  # solo temi ricorrenti (≥2)
    except Exception as e:
        print(f"[SENDER HISTORY] error: {e}")
    return out


def delete_account_data(account_id: int) -> dict:
    """
    Cancella TUTTI i dati indicizzati di un account: threads, indice FTS,
    embeddings, indexer_state. Usata dalla DELETE /accounts/{id}.
    Le mail sui server (Microsoft/IMAP) non vengono toccate.
    """
    deleted = {"threads": 0, "embeddings": 0}
    try:
        with _get_conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM threads WHERE account_id=?", (account_id,)
            ).fetchone()
            deleted["threads"] = int(row[0] if row else 0)
            row = conn.execute(
                "SELECT COUNT(*) FROM embeddings WHERE account_id=?", (account_id,)
            ).fetchone()
            deleted["embeddings"] = int(row[0] if row else 0)

            conn.execute("DELETE FROM embeddings WHERE account_id=?", (account_id,))
            conn.execute("DELETE FROM threads WHERE account_id=?", (account_id,))
            conn.execute("DELETE FROM indexer_state WHERE account_id=?", (account_id,))
            # L'FTS (external content) non ha delete-trigger: rebuild per
            # eliminare le righe orfane dall'indice di ricerca.
            conn.execute("INSERT INTO threads_fts(threads_fts) VALUES('rebuild')")
            conn.commit()
        print(f"[MAIL MEMORY] delete_account_data account {account_id}: "
              f"{deleted['threads']} threads, {deleted['embeddings']} embeddings rimossi")
    except Exception as e:
        print(f"[MAIL MEMORY] delete_account_data error: {e}")
    return deleted
