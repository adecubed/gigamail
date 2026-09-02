"""L'audit dice cosa ha fatto il server, non cosa abbiamo chiesto.

r/mcp (ranbuman, 2026-08-19): scritto dal payload approvato, l'audit
diceva "1 destinatario" per sempre, qualunque cosa il server avesse fatto
dopo. SMTP risponde a ogni RCPT TO: il conteggio accettato e' conoscibile
anche quando un gruppo nasconde i membri dietro un indirizzo. Ora
smtplib.sendmail() non viene piu' buttato: i RCPT rifiutati finiscono in
provider_result, accanto — non al posto — del payload approvato, sia
nell'audit sia sulla riga dell'approvazione (execution_outcome).

Stesso commit: TLS SMTP verificato di default (era CERT_NONE su 465);
opt-out esplicito per account con insecure_tls.
"""
import json
import ssl
import types

import pytest

from ade_mail_agent import policy
from ade_mail_agent.core import imap_client


@pytest.fixture(autouse=True)
def store_isolato(tmp_path):
    policy.set_store(policy.ApprovalStore(tmp_path / "approvals.db"))
    yield
    policy.set_store(None)


class _FakeSMTP:
    """smtplib.SMTP/SMTP_SSL finto: registra il contesto TLS e simula i
    RCPT rifiutati che `refused_map` dichiara."""
    instances = []

    def __init__(self, host, port, context=None, **kw):
        self.host, self.port, self.context = host, port, context
        self.starttls_context = None
        self.sent = None
        _FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self, context=None):
        self.starttls_context = context

    def login(self, u, p):
        pass

    def sendmail(self, from_addr, to_addrs, msg):
        self.sent = list(to_addrs)
        return {r: (550, b"5.1.1 User unknown") for r in to_addrs
                if r in _FakeSMTP.refused}


@pytest.fixture
def fake_smtp(monkeypatch):
    _FakeSMTP.instances = []
    _FakeSMTP.refused = set()
    monkeypatch.setattr(imap_client.smtplib, "SMTP_SSL", _FakeSMTP)
    monkeypatch.setattr(imap_client.smtplib, "SMTP", _FakeSMTP)
    monkeypatch.setattr(imap_client, "_append_to_sent_folder", lambda *a, **k: True)
    return _FakeSMTP


def _send(**kw):
    return imap_client.send_message(
        "smtp.example.it", kw.pop("port", 465), "me@example.it", "pw",
        "a@x.it", "s", "b", cc=["b@x.it", "c@x.it"], **kw)


# ------------------------------------------------------ provider_result SMTP

def test_tutti_accettati(fake_smtp):
    r = _send()
    pr = r["provider_result"]
    assert r["success"] is True
    assert pr["requested"] == 3 and pr["accepted"] == 3
    assert pr["refused"] == {}
    assert pr["tls_verified"] is True


def test_rifiutati_dal_server_contati_dalla_risposta(fake_smtp):
    """Chiesti 3, il server ne rifiuta 1: l'audit deve dire 2, non 3."""
    fake_smtp.refused = {"c@x.it"}
    r = _send()
    pr = r["provider_result"]
    assert pr["requested"] == 3
    assert pr["accepted"] == 2
    assert pr["accepted_recipients"] == ["a@x.it", "b@x.it"]
    assert pr["refused"]["c@x.it"]["code"] == 550
    assert "rifiutat" in (r["warning"] or "")
    assert r["success"] is True  # qualcuno l'ha ricevuta


def test_tutti_rifiutati_e_un_fallimento(fake_smtp):
    fake_smtp.refused = {"a@x.it", "b@x.it", "c@x.it"}
    r = _send()
    assert r["success"] is False
    assert r["provider_result"]["accepted"] == 0


# ---------------------------------------------------------------- TLS (B4)

def test_tls_verificato_di_default_465(fake_smtp):
    _send(port=465)
    ctx = fake_smtp.instances[-1].context
    assert ctx.verify_mode == ssl.CERT_REQUIRED
    assert ctx.check_hostname is True


def test_tls_verificato_di_default_587_starttls(fake_smtp):
    _send(port=587)
    inst = fake_smtp.instances[-1]
    assert inst.starttls_context is not None
    assert inst.starttls_context.verify_mode == ssl.CERT_REQUIRED


def test_insecure_tls_solo_se_esplicito(fake_smtp):
    _send(insecure_tls=True)
    ctx = fake_smtp.instances[-1].context
    assert ctx.verify_mode == ssl.CERT_NONE
    assert _send(insecure_tls=True)["provider_result"]["tls_verified"] is False


# ----------------------------------------------- riga approvazione + audit

def _phase1_then_approve():
    args = {"to": "a@x.it", "subject": "s", "body": "b", "cc": None, "bcc": None,
            "account_id": None}
    r1 = policy.execute_dangerous("send_mail", args, None,
                                  preview_fn=lambda: {}, execute_fn=lambda a: None)
    rid = r1["request_id"]
    policy.store().approve(rid, by="test")
    return rid, args


def _read_audit():
    p = policy._audit_path()
    if not p.exists():
        return []
    return [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]


def test_audit_e_riga_riportano_la_risposta_del_provider(monkeypatch):
    monkeypatch.delenv("ADE_MAIL_DRYRUN", raising=False)
    rid, args = _phase1_then_approve()
    provider_result = {"provider": "smtp", "requested": 3, "accepted": 2,
                       "refused": {"c@x.it": {"code": 550, "message": "unknown"}}}
    policy.execute_dangerous(
        "send_mail", args, rid, preview_fn=lambda: {},
        execute_fn=lambda a: {"success": True, "provider_result": provider_result})
    row = policy.store().get(rid)
    assert row["status"] == policy.EXECUTED
    assert row["execution_outcome"] == "ok"
    assert row["provider_result"]["accepted"] == 2
    last = [e for e in _read_audit() if e["tool"] == "send_mail" and e["outcome"] == "executed"][-1]
    # accanto al payload (args) c'e' la risposta del server
    assert last["args"]["to"] == "a@x.it"
    assert last["provider_result"]["accepted"] == 2
    assert "c@x.it" in last["provider_result"]["refused"]


def test_esecuzione_fallita_sulla_riga(monkeypatch):
    monkeypatch.delenv("ADE_MAIL_DRYRUN", raising=False)
    rid, args = _phase1_then_approve()
    with pytest.raises(RuntimeError):
        policy.execute_dangerous(
            "send_mail", args, rid, preview_fn=lambda: {},
            execute_fn=lambda a: (_ for _ in ()).throw(RuntimeError("smtp down")))
    row = policy.store().get(rid)
    assert row["status"] == policy.EXECUTED  # consumata PRIMA (at-most-once)
    assert row["execution_outcome"] == "failed"
    assert "smtp down" in row["provider_result"]["error"]


def test_success_false_dal_provider_e_failed(monkeypatch):
    monkeypatch.delenv("ADE_MAIL_DRYRUN", raising=False)
    rid, args = _phase1_then_approve()
    policy.execute_dangerous(
        "send_mail", args, rid, preview_fn=lambda: {},
        execute_fn=lambda a: {"success": False, "error": "550",
                              "provider_result": {"accepted": 0}})
    row = policy.store().get(rid)
    assert row["execution_outcome"] == "failed"
    last = [e for e in _read_audit() if e["tool"] == "send_mail"][-1]
    assert last["outcome"] == "executed_with_error"


def test_dryrun_segnato_sulla_riga(monkeypatch):
    monkeypatch.setenv("ADE_MAIL_DRYRUN", "1")
    rid, args = _phase1_then_approve()
    policy.execute_dangerous("send_mail", args, rid, preview_fn=lambda: {},
                             execute_fn=lambda a: {"success": True})
    assert policy.store().get(rid)["execution_outcome"] == "dryrun"


# ----------------------------------------------------------------- Graph

def test_graph_dichiara_che_non_verifica_per_destinatario(monkeypatch):
    from ade_mail_agent.core import mail as ms_mail
    fake_res = types.SimpleNamespace(status_code=202, text="", headers={"request-id": "abc"})
    monkeypatch.setattr(ms_mail.requests, "post", lambda *a, **k: fake_res)
    monkeypatch.setattr(ms_mail, "_headers", lambda: {})
    r = ms_mail.send_message("a@x.it", "s", "b", cc=["b@x.it"])
    pr = r["provider_result"]
    assert r["success"] is True
    assert pr["provider"] == "graph" and pr["http_status"] == 202
    assert pr["requested"] == 2
    assert pr["accepted"] is None and pr["per_recipient_verified"] is False
    assert pr["request_id"] == "abc"
