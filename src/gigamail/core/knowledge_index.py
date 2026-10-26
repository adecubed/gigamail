"""
knowledge_index.py — Content search over the knowledge files the user
registered.

identity_reader picks files by NAME: a price that only appears inside a
list, or on row 400 of a long one, never reached the agent, and the draft
either stalled or made it up. Here the files are cut into chunks and
indexed with SQLite FTS5, locally, so a passage is found by what it says.

Whitelist: the index can hold files of any account, but every search is
limited to the files the caller is allowed to see (the registered paths,
expanded by identity_reader.list_all_files), so a file indexed and later
unregistered never comes out.
"""

import logging
import os
import re
import sqlite3
import threading
from typing import Dict, List, Optional

from . import file_extractor
from .data_paths import db_path as _db_path

logger = logging.getLogger(__name__)

_DB_NAME = ".knowledge_index.db"
_LOCK = threading.Lock()
_SCHEMA_READY = False
_FTS_AVAILABLE = True

CHUNK_CHARS = 800
# A file larger than this is indexed up to here: a knowledge file is a
# price list or a set of terms, not a book.
_MAX_TEXT_CHARS = 2_000_000
_MAX_QUERY_TOKENS = 30
# Codes weigh more than words: "X.4.2" names one apartment, "price"
# appears in every row.
_CODES_WEIGHT = 8.0

_TEXT_EXTENSIONS = {'.txt', '.md', '.csv', '.xlsx', '.xls', '.pdf', '.docx'}
_SHEET_LINE = re.compile(r"^\[Foglio: .*\]$")
# Same shape as identity_reader.find_relevant_files, without whitespace as a
# separator: in running text "via 10" or "mq 80" would become codes.
_CODE = re.compile(r"\b[a-z]{1,3}[._\-]?\d+(?:[._\-]\d+)*\b")
_WORD = re.compile(r"[^\W\d_]{3,}")
_STOPWORDS = {
    "che", "per", "con", "del", "della", "delle", "dei", "degli", "una",
    "uno", "non", "sono", "come", "anche", "alla", "alle", "nel", "nella",
    "dal", "dalla", "gli", "questo", "questa", "buongiorno", "salve",
    "grazie", "cordiali", "saluti", "the", "and", "for", "with", "you",
    "your", "are", "this", "that", "from", "have", "thanks", "regards",
    "hello", "dear",
}


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_db_path(_DB_NAME)), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> bool:
    """Create the tables once per process. False when this SQLite has no
    FTS5: callers then fall back to what they did before."""
    global _SCHEMA_READY, _FTS_AVAILABLE
    if _SCHEMA_READY:
        return _FTS_AVAILABLE
    conn.execute(
        "CREATE TABLE IF NOT EXISTS files ("
        " path TEXT PRIMARY KEY, mtime REAL, size INTEGER,"
        " error TEXT NOT NULL DEFAULT '')")
    try:
        conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5("
            " text, codes, path UNINDEXED, ord UNINDEXED,"
            " tokenize='unicode61 remove_diacritics 2')")
    except sqlite3.OperationalError as e:
        logger.warning("FTS5 not available, knowledge search off: %s", e)
        _FTS_AVAILABLE = False
    conn.commit()
    _SCHEMA_READY = True
    return _FTS_AVAILABLE


def _norm_code(code: str) -> str:
    return re.sub(r"[^a-z0-9]", "", code.lower())


def codes_in(text: str) -> List[str]:
    """Codes in a text, normalised: 'X.4.2', 'x-4-2' and 'X42' -> 'x42'."""
    seen: List[str] = []
    for c in _CODE.findall((text or "").lower()):
        n = _norm_code(c)
        if n and n not in seen:
            seen.append(n)
    return seen


def _split_long(line: str, size: int) -> List[str]:
    """A line longer than a chunk (a PDF paragraph with no line breaks),
    cut at the last space before the limit."""
    pieces = []
    while len(line) > size:
        cut = line.rfind(" ", 0, size)
        if cut <= size // 2:
            cut = size
        pieces.append(line[:cut].strip())
        line = line[cut:].strip()
    if line:
        pieces.append(line)
    return pieces


def chunk_text(text: str, csv_header: bool = False,
               size: int = CHUNK_CHARS) -> List[str]:
    """Cut text into chunks of about `size` characters on line boundaries,
    so a spreadsheet row is never split. In a spreadsheet every chunk
    repeats the sheet label and the header row: row 300 with "120.000"
    is useless without "Code | Sqm | Price"."""
    chunks: List[str] = []
    context = ""
    buf: List[str] = []
    used = 0
    header_pending = False

    def flush():
        nonlocal buf, used
        if buf:
            chunks.append("\n".join(([context] if context else []) + buf))
        buf, used = [], 0

    lines = (text or "").splitlines()
    if csv_header and lines:
        context = lines[0].strip()
        lines = lines[1:]
    for raw in lines:
        line = raw.strip()
        if not line:
            if used >= size // 2:
                flush()
            continue
        if _SHEET_LINE.match(line):
            flush()
            context, header_pending = line, True
            continue
        if header_pending:
            context = f"{context}\n{line}"
            header_pending = False
            continue
        for piece in _split_long(line, size):
            if buf and used + len(piece) > size:
                flush()
            buf.append(piece)
            used += len(piece) + 1
    flush()
    return chunks


def allowed_files(paths: List[str]) -> List[Dict]:
    """The readable text files behind the registered paths: the same
    expansion list_knowledge_files shows, images left out."""
    from . import identity_reader
    out = []
    for f in identity_reader.list_all_files(list(paths or [])):
        if f.get("ext") in _TEXT_EXTENSIONS:
            f = dict(f)
            f["key"] = os.path.abspath(f["path"])
            out.append(f)
    return out


def _index_file(conn: sqlite3.Connection, key: str, name: str,
                mtime: float, size: int) -> None:
    conn.execute("DELETE FROM chunks_fts WHERE path=?", (key,))
    error = ""
    chunks: List[str] = []
    try:
        text, _kind = file_extractor.extract_text(key, original_filename=name)
        text = str(text or "")[:_MAX_TEXT_CHARS]
        chunks = chunk_text(text, csv_header=name.lower().endswith(".csv"))
    except Exception as e:
        # The error text never goes into the index: it would come back as
        # the content of the file, under the label of reliable data.
        logger.warning("knowledge file not readable %s: %s", key, e)
        error = str(e)[:500] or e.__class__.__name__
    for i, chunk in enumerate(chunks):
        conn.execute(
            "INSERT INTO chunks_fts(text, codes, path, ord) VALUES (?,?,?,?)",
            (chunk, " ".join(codes_in(chunk)), key, i))
    conn.execute(
        "INSERT OR REPLACE INTO files(path, mtime, size, error) VALUES (?,?,?,?)",
        (key, mtime, size, error))


def ensure_indexed(paths: List[str]) -> List[Dict]:
    """Index what changed among the allowed files (by mtime and size) and
    drop the files gone from disk. Returns the allowed files."""
    files = allowed_files(paths)
    with _LOCK, _conn() as conn:
        if not _ensure_schema(conn):
            return files
        known = {r["path"]: (r["mtime"], r["size"])
                 for r in conn.execute("SELECT path, mtime, size FROM files")}
        for f in files:
            try:
                st = os.stat(f["key"])
            except OSError:
                continue
            if known.get(f["key"]) != (st.st_mtime, st.st_size):
                _index_file(conn, f["key"], f["name"], st.st_mtime, st.st_size)
        for key in known:
            if not os.path.exists(key):
                conn.execute("DELETE FROM chunks_fts WHERE path=?", (key,))
                conn.execute("DELETE FROM files WHERE path=?", (key,))
    return files


def match_expression(query: str) -> str:
    """FTS5 expression from free text (often a whole mail). Every token is
    letters or digits only and quoted, so quotes, `*`, NEAR or OR in the
    mail never become FTS operators."""
    q = (query or "").lower()
    tokens: List[str] = []
    for code in codes_in(q):
        tokens.append(code)
    for word in _WORD.findall(q):
        if word not in _STOPWORDS and word not in tokens:
            tokens.append(word)
    tokens = tokens[:_MAX_QUERY_TOKENS]
    return " OR ".join(f'"{t}"' for t in tokens)


def search(paths: List[str], query: str, limit: int = 5) -> List[Dict]:
    """The chunks most relevant to `query` among the allowed files, best
    first: [{name, path, excerpt, score, ord}]. [] without FTS5, without
    a usable query or without allowed files."""
    files = ensure_indexed(paths)
    allowed = {f["key"]: f for f in files}
    match = match_expression(query)
    if not allowed or not match or not _FTS_AVAILABLE:
        return []
    keys = list(allowed)
    marks = ",".join("?" * len(keys))
    try:
        with _LOCK, _conn() as conn:
            rows = conn.execute(
                "SELECT path, ord, text, bm25(chunks_fts, 1.0, ?) AS rank"
                " FROM chunks_fts WHERE chunks_fts MATCH ?"
                f" AND path IN ({marks}) ORDER BY rank LIMIT ?",
                (_CODES_WEIGHT, match, *keys, max(1, int(limit)))).fetchall()
    except sqlite3.Error as e:
        logger.warning("knowledge search failed: %s", e)
        return []
    return [{"name": allowed[r["path"]]["name"], "path": r["path"],
             "excerpt": r["text"], "score": round(-float(r["rank"]), 3),
             "ord": int(r["ord"])}
            for r in rows]


def relevant_excerpts(path: str, query: str, max_chars: int,
                      limit: int = 20) -> Optional[str]:
    """The passages of ONE file most relevant to `query`, in document
    order, within `max_chars`. None when nothing matches."""
    hits = search([path], query, limit=limit)
    picked, used = [], 0
    for h in hits:
        if used + len(h["excerpt"]) > max_chars:
            continue
        picked.append(h)
        used += len(h["excerpt"]) + 7
    if not picked:
        return None
    picked.sort(key=lambda h: h["ord"])
    return "\n[...]\n".join(h["excerpt"] for h in picked)
