"""Archivio approvazioni non raggiungibile = DINIEGO ESPLICITO, non crash.

r/mcp (ranbuman, 2026-08-21): far propagare l'eccezione e' il comportamento
giusto, con un rischio di lungo periodo. Un'eccezione nuda da uno store
mancante sembra esattamente un bug, e il prossimo che la vede nei log la
avvolge in un try/except per zittire il rumore — cosi' il gate diventa
fail-open dentro un commit che si legge come pulizia.

Un diniego con un suo codice (`store_unavailable`) non e' sicurezza
migliore oggi. E' cio' che impedisce a quel commit di essere scritto:
questi test diventano rossi se qualcuno lo "ripulisce".
"""
import sqlite3

import pytest

from ade_mail_agent import policy


@pytest.fixture()
def store_rotto(tmp_path):
    """Store valido alla costruzione, irraggiungibile alle chiamate: e' il
    caso reale (file cancellato, DB lockato, permessi tolti a caldo)."""
    s = policy.ApprovalStore(tmp_path / "approvals.db")
    policy.set_store(s)
    yield s
    policy.set_store(None)


def _rompi(s, monkeypatch):
    def _boom(*a, **k):
        raise sqlite3.OperationalError("unable to open database file")
    monkeypatch.setattr(s, "_conn", _boom)


def _fase1(execute_fn=None):
    return policy.execute_dangerous(
        "send_mail", {"to": "a@x.it", "subject": "s", "body": "b"}, None,
        preview_fn=lambda: {"to": "a@x.it"},
        execute_fn=execute_fn or (lambda a: None))


# --------------------------------------------------------------- fase 1

def test_fase1_nega_esplicitamente(store_rotto, monkeypatch):
    _rompi(store_rotto, monkeypatch)
    r = _fase1()
    assert r["status"] == policy.STORE_UNAVAILABLE
    assert r["request_id"] is None


def test_fase1_non_solleva(store_rotto, monkeypatch):
    """Il punto dell'esercizio: e' una risposta deliberata, non un crash —
    cosi' nessuno la scambia per rumore da zittire."""
    _rompi(store_rotto, monkeypatch)
    _fase1()  # se solleva, il test fallisce da solo


def test_fase1_nega_anche_se_l_audit_non_scrive(store_rotto, monkeypatch, tmp_path):
    """Se salta pure la cartella dati, il diniego resta un diniego."""
    _rompi(store_rotto, monkeypatch)
    def _audit_boom(*a, **k):
        raise OSError("read-only file system")
    monkeypatch.setattr(policy, "audit", _audit_boom)
    assert _fase1()["status"] == policy.STORE_UNAVAILABLE


# --------------------------------------------------------------- fase 2

def test_fase2_non_esegue_mai(store_rotto, monkeypatch):
    """Richiesta creata e approvata regolarmente; poi lo store sparisce.
    La fase 2 deve negare SENZA chiamare execute_fn."""
    rid = _fase1()["request_id"]
    assert store_rotto.approve(rid, by="test")
    eseguito = []
    _rompi(store_rotto, monkeypatch)
    r = policy.execute_dangerous(
        "send_mail", {}, rid, preview_fn=lambda: {},
        execute_fn=lambda a: eseguito.append(a))
    assert r["status"] == policy.STORE_UNAVAILABLE
    assert eseguito == [], "azione eseguita senza poter leggere l'approvazione"


def test_fase2_nega_anche_al_consumo(store_rotto, monkeypatch):
    """Lo store regge la lettura del record ma cade sul consume: comunque
    nessuna esecuzione (il consume e' cio' che rende at-most-once)."""
    rid = _fase1()["request_id"]
    store_rotto.approve(rid, by="test")
    eseguito = []
    def _boom(*a, **k):
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(store_rotto, "consume_approved", _boom)
    r = policy.execute_dangerous(
        "send_mail", {}, rid, preview_fn=lambda: {},
        execute_fn=lambda a: eseguito.append(a))
    assert r["status"] == policy.STORE_UNAVAILABLE
    assert eseguito == []


# ------------------------------------------------------- il caso onesto

def test_db_cancellato_e_processo_riavviato_azzera_il_cap(tmp_path):
    """Documentato in SECURITY.md: cancellare il DB e riavviare il processo
    ricrea lo schema vuoto, quindi il contatore orario riparte da zero. Ma
    lo stesso gesto porta via ogni riga pending e approved: il cap si
    azzera, il gate no. Il cap limita la CREAZIONE di richieste, non e' un
    confine di sicurezza — il confine e' l'approvazione piu' il prompt OS."""
    db = tmp_path / "approvals.db"
    policy.set_store(policy.ApprovalStore(db))
    try:
        rid = _fase1()["request_id"]
        policy.store().approve(rid, by="test")
        assert policy.store().get(rid)["status"] == policy.APPROVED
        db.unlink()
        policy.set_store(policy.ApprovalStore(db))  # riavvio
        assert policy.store().count_created_since("send_mail", 0) == 0
        assert policy.store().get(rid) is None, "l'approvazione e' sopravvissuta"
    finally:
        policy.set_store(None)
