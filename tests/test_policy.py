"""Approvazione fuori banda: il cuore del modello di sicurezza.

Garanzia: l'agente riceve solo un riferimento inerte (request_id).
L'esecuzione richiede un'approvazione data attraverso un canale che l'agente
non raggiunge (console/CLI). Ripetere il request_id non esegue nulla.
"""
import json

import pytest

from ade_mail_agent import policy


@pytest.fixture(autouse=True)
def isolated_store(tmp_path):
    policy.set_store(policy.ApprovalStore(tmp_path / "approvals.db"))
    yield
    policy.set_store(None)


def _preview():
    return {"to": "x@y.it", "subject": "test"}


def _fase1(tool="send_mail", args=None):
    return policy.execute_dangerous(
        tool, args or {"to": "x@y.it", "body": "ciao"}, None,
        preview_fn=_preview, execute_fn=lambda a: a,
    )


def test_fase1_non_restituisce_nessun_segreto():
    """IL PUNTO: nel risultato non deve esserci nulla che l'agente possa
    usare da solo per eseguire (niente confirm_token)."""
    r = _fase1()
    assert r["status"] == "approval_required"
    assert "confirm_token" not in r
    assert r["request_id"].startswith("req_")
    blob = json.dumps(r)
    assert "token" not in blob.lower()


def test_fase1_non_esegue():
    executed = []
    policy.execute_dangerous("send_mail", {"to": "x@y.it"}, None,
                             _preview, lambda a: executed.append(a))
    assert executed == []


def test_request_id_da_solo_non_esegue():
    """Anche riusandolo all'infinito: senza approvazione umana non parte."""
    r = _fase1()
    executed = []
    for _ in range(5):
        out = policy.execute_dangerous(
            "send_mail", {}, r["request_id"], _preview,
            lambda a: executed.append(a),
        )
        assert out["status"] == "awaiting_approval"
    assert executed == []


def test_esegue_solo_dopo_approvazione_umana():
    r = _fase1()
    assert policy.store().approve(r["request_id"]) is True
    out = policy.execute_dangerous("send_mail", {}, r["request_id"],
                                   _preview, lambda a: {"sent": a})
    assert out == {"sent": {"to": "x@y.it", "body": "ciao"}}


def test_esegue_gli_args_canonici_non_quelli_ripassati():
    """L'agente non puo' cambiare destinatario tra richiesta ed esecuzione."""
    r = _fase1(args={"to": "legittimo@cliente.it", "body": "ok"})
    policy.store().approve(r["request_id"])
    out = policy.execute_dangerous(
        "send_mail", {"to": "ATTACCANTE@evil.it", "body": "manomesso"},
        r["request_id"], _preview, lambda a: a,
    )
    assert out["to"] == "legittimo@cliente.it"
    assert out["body"] == "ok"


def test_approvazione_monouso():
    r = _fase1()
    policy.store().approve(r["request_id"])
    policy.execute_dangerous("send_mail", {}, r["request_id"], _preview, lambda a: "ok")
    with pytest.raises(ValueError):
        policy.execute_dangerous("send_mail", {}, r["request_id"], _preview, lambda a: "ok")


def test_request_id_di_un_tool_non_vale_per_un_altro():
    r = _fase1()
    policy.store().approve(r["request_id"])
    with pytest.raises(ValueError):
        policy.execute_dangerous("delete_message", {}, r["request_id"],
                                 _preview, lambda a: "ok")


def test_request_id_inventato_rifiutato():
    with pytest.raises(ValueError):
        policy.execute_dangerous("send_mail", {}, "req_inventato",
                                 _preview, lambda a: "ok")


def test_richiesta_scaduta_non_approvabile_ne_eseguibile():
    store = policy.store()
    rid = store.create("send_mail", {"to": "x@y.it"}, _preview(), ttl=-1)
    assert store.approve(rid) is False
    with pytest.raises(ValueError):
        policy.execute_dangerous("send_mail", {}, rid, _preview, lambda a: "ok")


def test_rifiuto_blocca_esecuzione():
    r = _fase1()
    assert policy.store().reject(r["request_id"]) is True
    out = policy.execute_dangerous("send_mail", {}, r["request_id"],
                                   _preview, lambda a: "ESEGUITO")
    assert out["status"] == "rejected"


def test_pending_visibile_al_canale_umano():
    r = _fase1()
    pending = policy.store().list_pending()
    assert [p["request_id"] for p in pending] == [r["request_id"]]
    assert pending[0]["preview"] == _preview()
    policy.store().approve(r["request_id"])
    assert policy.store().list_pending() == []


def test_stato_condiviso_tra_processi(tmp_path):
    """La console approva in un processo, il server MCP esegue in un altro:
    lo stato deve stare su disco, non in memoria."""
    db = tmp_path / "shared.db"
    policy.set_store(policy.ApprovalStore(db))
    r = _fase1()
    # "altro processo": store nuovo sullo stesso file
    policy.set_store(policy.ApprovalStore(db))
    assert policy.store().approve(r["request_id"]) is True
    policy.set_store(policy.ApprovalStore(db))
    out = policy.execute_dangerous("send_mail", {}, r["request_id"],
                                   _preview, lambda a: "ok")
    assert out == "ok"


def _read_audit():
    with open(policy._audit_path(), encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def test_audit_traccia_richiesta_approvazione_ed_esecuzione():
    r = _fase1()
    policy.store().approve(r["request_id"])
    policy.execute_dangerous("send_mail", {}, r["request_id"], _preview, lambda a: "ok")
    esiti = [e["outcome"] for e in _read_audit()][-3:]
    assert esiti == ["approval_requested", "approved", "executed"]


def test_audit_non_registra_il_corpo_della_mail():
    policy.execute_dangerous("send_mail", {"to": "x@y.it", "body": "SEGRETO"},
                             None, _preview, lambda a: "ok")
    assert "body" not in _read_audit()[-1]["args"]


def test_errore_esecuzione_propagato_e_auditato():
    r = _fase1()
    policy.store().approve(r["request_id"])

    def boom(a):
        raise RuntimeError("smtp giu")

    with pytest.raises(RuntimeError):
        policy.execute_dangerous("send_mail", {}, r["request_id"], _preview, boom)
    assert _read_audit()[-1]["outcome"] == "error"


def test_dryrun_blocca_esecuzione_anche_se_approvata(monkeypatch):
    monkeypatch.setenv("ADE_MAIL_DRYRUN", "1")
    r = _fase1()
    policy.store().approve(r["request_id"])
    executed = []
    out = policy.execute_dangerous("send_mail", {}, r["request_id"],
                                   _preview, lambda a: executed.append(a))
    assert out.get("dryrun") is True
    assert executed == []
    assert _read_audit()[-1]["outcome"] == "dryrun_executed"
