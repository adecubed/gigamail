"""
observer.py — Osserva e impara dalle modifiche dell'utente alle bozze mail.
Salva in SQLite locale i pattern di modifica e li usa per migliorare le bozze future.

v2: aggiunto template learning per mail simili (per dominio mittente + keywords oggetto).
"""

import os
import re
import sqlite3
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from .data_paths import db_path as _db_path

DB_PATH = str(_db_path('.observer.db'))

# Stopwords per keyword extraction
_STOP = {
    "re", "fw", "fwd", "i", "il", "la", "lo", "le", "gli", "un", "una",
    "per", "con", "che", "del", "della", "dei", "degli", "delle", "dal",
    "dalla", "dai", "dalle", "sul", "sulla", "sui", "sulle", "nel", "nella",
    "nei", "nelle", "and", "the", "for", "you", "your", "this", "that",
    "mail", "email", "messaggio", "risposta", "grazie", "saluti", "cordiali",
}


def _init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS interactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER,
                sender TEXT,
                subject TEXT,
                original_draft TEXT,
                final_text TEXT,
                instruction TEXT,
                sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS patterns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER,
                pattern_type TEXT,
                pattern_value TEXT,
                frequency INTEGER DEFAULT 1,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        # Tabella template per mail simili
        conn.execute('''
            CREATE TABLE IF NOT EXISTS templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                sender_domain TEXT,
                sender_email TEXT,
                subject_keywords TEXT,        -- JSON array di keywords
                template_text TEXT NOT NULL,
                instruction TEXT,
                frequency INTEGER DEFAULT 1,
                last_used TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.execute('''
            CREATE INDEX IF NOT EXISTS idx_templates_account
            ON templates(account_id, sender_domain)
        ''')
        conn.commit()


_init_db()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_domain(email: str) -> str:
    """Estrae dominio da indirizzo email."""
    email = (email or "").strip().lower()
    if "@" in email:
        return email.split("@", 1)[1]
    return ""


def _extract_keywords(text: str, max_kw: int = 8) -> List[str]:
    """Estrae keywords significative da un testo (oggetto mail)."""
    words = re.findall(r"[a-zàèéìòù]{4,}", (text or "").lower())
    seen = set()
    out = []
    for w in words:
        if w not in _STOP and w not in seen:
            seen.add(w)
            out.append(w)
        if len(out) >= max_kw:
            break
    return out


def _keyword_overlap(kw_a: List[str], kw_b: List[str]) -> float:
    """Score di sovrapposizione tra due liste di keywords (0.0 – 1.0)."""
    if not kw_a or not kw_b:
        return 0.0
    set_a, set_b = set(kw_a), set(kw_b)
    intersection = set_a & set_b
    union = set_a | set_b
    return len(intersection) / len(union)


# ── Core API ──────────────────────────────────────────────────────────────────

def log_interaction(account_id: int, sender: str, subject: str,
                    original_draft: str, final_text: str, instruction: str):
    """Salva una interazione e aggiorna i pattern di stile."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('''
            INSERT INTO interactions
            (account_id, sender, subject, original_draft, final_text, instruction)
            VALUES (?,?,?,?,?,?)
        ''', (account_id, sender, subject, original_draft, final_text, instruction))
        conn.commit()

    _update_patterns(account_id, original_draft, final_text)


def learn_template(
    account_id: int,
    sender: str,
    subject: str,
    reply_text: str,
    instruction: str = "",
) -> None:
    """
    Impara la risposta inviata come template per mail future simili.
    Raggruppa per dominio mittente + keywords oggetto.
    Se esiste un template simile (overlap > 0.5), incrementa frequency e aggiorna il testo.
    Altrimenti crea un nuovo template.
    """
    if not reply_text or len(reply_text.strip()) < 20:
        return

    domain = _extract_domain(sender)
    kw_new = _extract_keywords(subject)
    kw_json = __import__("json").dumps(kw_new, ensure_ascii=False)

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row

        # Cerca template esistenti stesso account + stesso dominio
        candidates = conn.execute('''
            SELECT id, subject_keywords, frequency
            FROM templates
            WHERE account_id=? AND sender_domain=?
            ORDER BY frequency DESC
            LIMIT 20
        ''', (account_id, domain)).fetchall()

        best_id = None
        best_score = 0.0

        for row in candidates:
            try:
                kw_existing = __import__("json").loads(row["subject_keywords"] or "[]")
            except Exception:
                kw_existing = []
            score = _keyword_overlap(kw_new, kw_existing)
            if score > best_score:
                best_score = score
                best_id = row["id"]

        if best_id and best_score >= 0.5:
            # Aggiorna template esistente
            conn.execute('''
                UPDATE templates
                SET template_text=?, instruction=?, frequency=frequency+1, last_used=?
                WHERE id=?
            ''', (reply_text, instruction, datetime.utcnow(), best_id))
        else:
            # Crea nuovo template
            conn.execute('''
                INSERT INTO templates
                (account_id, sender_domain, sender_email, subject_keywords,
                 template_text, instruction)
                VALUES (?,?,?,?,?,?)
            ''', (account_id, domain, sender.lower().strip(),
                  kw_json, reply_text, instruction))

        conn.commit()


def find_similar_template(
    account_id: int,
    sender: str,
    subject: str,
    min_frequency: int = 1,
    min_overlap: float = 0.3,
) -> Optional[Dict]:
    """
    Cerca un template simile per una mail in arrivo.
    Priorità: stesso mittente esatto > stesso dominio + keywords > solo dominio.

    Returns:
        Dict con {template_text, instruction, frequency, score} oppure None.
    """
    domain = _extract_domain(sender)
    sender_clean = sender.lower().strip()
    kw_incoming = _extract_keywords(subject)

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row

        # 1. Match esatto mittente (priorità massima)
        exact = conn.execute('''
            SELECT template_text, instruction, frequency, subject_keywords
            FROM templates
            WHERE account_id=? AND sender_email=? AND frequency>=?
            ORDER BY frequency DESC, last_used DESC
            LIMIT 1
        ''', (account_id, sender_clean, min_frequency)).fetchone()

        if exact:
            return {
                "template_text": exact["template_text"],
                "instruction": exact["instruction"] or "",
                "frequency": exact["frequency"],
                "score": 1.0,
                "match_type": "exact_sender",
            }

        # 2. Match dominio + keywords
        candidates = conn.execute('''
            SELECT id, template_text, instruction, frequency, subject_keywords
            FROM templates
            WHERE account_id=? AND sender_domain=? AND frequency>=?
            ORDER BY frequency DESC, last_used DESC
            LIMIT 20
        ''', (account_id, domain, min_frequency)).fetchall()

        best = None
        best_score = 0.0

        for row in candidates:
            try:
                kw_template = __import__("json").loads(row["subject_keywords"] or "[]")
            except Exception:
                kw_template = []
            score = _keyword_overlap(kw_incoming, kw_template)
            if score > best_score:
                best_score = score
                best = row

        if best and best_score >= min_overlap:
            return {
                "template_text": best["template_text"],
                "instruction": best["instruction"] or "",
                "frequency": best["frequency"],
                "score": round(best_score, 2),
                "match_type": "domain_keywords",
            }

        # 3. Fallback: solo dominio, template più usato
        if candidates:
            top = candidates[0]
            return {
                "template_text": top["template_text"],
                "instruction": top["instruction"] or "",
                "frequency": top["frequency"],
                "score": 0.1,
                "match_type": "domain_only",
            }

    return None


def get_context_for_prompt(account_id: int, sender: str = "", subject: str = "") -> str:
    """
    Ritorna un contesto da iniettare nel prompt LLM con:
    - pattern di stile appresi
    - template suggerito se disponibile
    """
    import json as _json

    with sqlite3.connect(DB_PATH) as conn:
        patterns = conn.execute('''
            SELECT pattern_type, pattern_value, frequency
            FROM patterns
            WHERE account_id=?
            ORDER BY frequency DESC
            LIMIT 30
        ''', (account_id,)).fetchall()

        interactions = conn.execute('''
            SELECT original_draft, final_text, instruction
            FROM interactions
            WHERE account_id=?
            ORDER BY sent_at DESC
            LIMIT 5
        ''', (account_id,)).fetchall()

    lines = []

    # Stile
    preferred = [p[1] for p in patterns if p[0] == 'preferred_word'][:10]
    avoided   = [p[1] for p in patterns if p[0] == 'avoided_word'][:10]
    length    = next((p[1] for p in patterns if p[0] == 'length_preference'), None)

    if preferred or avoided or length:
        lines.append('[PREFERENZE STILE UTENTE]:')
        if preferred:
            lines.append(f'- Usa spesso: {", ".join(preferred)}')
        if avoided:
            lines.append(f'- Evita: {", ".join(avoided)}')
        if length:
            lines.append(f'- Lunghezza preferita: {length}')

    # Esempi recenti
    if interactions:
        lines.append('\n[ESEMPI RISPOSTE RECENTI]:')
        for orig, final, instr in interactions[:3]:
            if instr:
                lines.append(f'  Istruzione: {instr}')
            lines.append(f'  Risposta inviata: {(final or "")[:200]}')

    # Template suggerito per questa mail specifica
    if sender or subject:
        tmpl = find_similar_template(account_id, sender, subject)
        if tmpl:
            match_label = {
                "exact_sender": "stesso mittente",
                "domain_keywords": f"stesso dominio + argomento simile (score {tmpl['score']})",
                "domain_only": "stesso dominio",
            }.get(tmpl["match_type"], "simile")
            lines.append(f'\n[TEMPLATE SUGGERITO — usato {tmpl["frequency"]} volte, match: {match_label}]:')
            lines.append(f'Usa questa risposta come base e adattala al contesto attuale:')
            lines.append(tmpl["template_text"][:600])
            if tmpl["instruction"]:
                lines.append(f'Istruzione originale: {tmpl["instruction"]}')

    return '\n'.join(lines)


# ── Pattern stile (invariato) ─────────────────────────────────────────────────

def _update_patterns(account_id: int, original: str, final: str):
    if not original or not final:
        return
    orig_words = set(original.lower().split())
    final_words = set(final.lower().split())
    added   = final_words - orig_words
    removed = orig_words - final_words

    with sqlite3.connect(DB_PATH) as conn:
        for word in added:
            if len(word) > 4:
                _upsert_pattern(conn, account_id, 'preferred_word', word)
        for word in removed:
            if len(word) > 4:
                _upsert_pattern(conn, account_id, 'avoided_word', word)
        final_len = len(final.split())
        if final_len < 50:
            _upsert_pattern(conn, account_id, 'length_preference', 'breve')
        elif final_len < 150:
            _upsert_pattern(conn, account_id, 'length_preference', 'medio')
        else:
            _upsert_pattern(conn, account_id, 'length_preference', 'lungo')
        conn.commit()


def _upsert_pattern(conn, account_id: int, pattern_type: str, pattern_value: str):
    existing = conn.execute(
        'SELECT id FROM patterns WHERE account_id=? AND pattern_type=? AND pattern_value=?',
        (account_id, pattern_type, pattern_value)
    ).fetchone()
    if existing:
        conn.execute(
            'UPDATE patterns SET frequency=frequency+1, updated_at=? WHERE id=?',
            (datetime.utcnow(), existing[0])
        )
    else:
        conn.execute(
            'INSERT INTO patterns (account_id, pattern_type, pattern_value) VALUES (?,?,?)',
            (account_id, pattern_type, pattern_value)
        )


def get_stats(account_id: int) -> Dict:
    with sqlite3.connect(DB_PATH) as conn:
        total = conn.execute(
            'SELECT COUNT(*) FROM interactions WHERE account_id=?', (account_id,)
        ).fetchone()[0]
        patterns_count = conn.execute(
            'SELECT COUNT(*) FROM patterns WHERE account_id=?', (account_id,)
        ).fetchone()[0]
        templates_count = conn.execute(
            'SELECT COUNT(*) FROM templates WHERE account_id=?', (account_id,)
        ).fetchone()[0]
    return {
        'interactions': total,
        'patterns': patterns_count,
        'templates': templates_count,
    }
