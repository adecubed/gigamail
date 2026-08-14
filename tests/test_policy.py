"""Policy a due fasi: il cuore del modello di sicurezza."""
import json

import pytest

from ade_mail_agent import policy


def _preview():
    return {"to": "x@y.it", "subject": "test"}


def test_fase1_restituisce_anteprima_e_token_senza_eseguire():
    executed = []
    r = policy.execute_dangerous(
        "send_mail", {"to": "x@y.it", "body": "ciao"}, None,
        preview_fn=_preview, execute_fn=lambda a: executed.append(a),
    )
    assert r["status"] == "confirmation_required"
    assert r["preview"] == _preview()
    assert r["confirm_token"]
    assert executed == []  # NULLA eseguito in fase 1


def test_fase2_esegue_con_gli_args_originali():
    r = policy.execute_dangerous(
        "send_mail", {"to": "x@y.it", "body": "originale"}, None,
        preview_fn=_preview, execute_fn=lambda a: a,
    )
    # la fase 2 ignora gli args passati ora e usa quelli registrati in fase 1
    out = policy.execute_dangerous(
        "send_mail", {"to": "ALTRO@z.it", "body": "manomesso"}, r["confirm_token"],
        preview_fn=_preview, execute_fn=lambda a: a,
    )
    assert out == {"to": "x@y.it", "body": "originale"}


def test_token_monouso_riuso_rifiutato():
    r = policy.execute_dangerous(
        "send_mail", {"to": "x@y.it"}, None,
        preview_fn=_preview, execute_fn=lambda a: "ok",
    )
    tok = r["confirm_token"]
    assert policy.execute_dangerous("send_mail", {}, tok, _preview, lambda a: "ok") == "ok"
    with pytest.raises(ValueError):
        policy.execute_dangerous("send_mail", {}, tok, _preview, lambda a: "ok")


def test_token_di_un_tool_non_vale_per_un_altro():
    r = policy.execute_dangerous(
        "send_mail", {"to": "x@y.it"}, None,
        preview_fn=_preview, execute_fn=lambda a: "ok",
    )
    with pytest.raises(ValueError):
        policy.execute_dangerous("delete_message", {}, r["confirm_token"], _preview, lambda a: "ok")


def test_token_scaduto_rifiutato(monkeypatch):
    r = policy.execute_dangerous(
        "send_mail", {"to": "x@y.it"}, None,
        preview_fn=_preview, execute_fn=lambda a: "ok",
    )
    import time as _time
    real = _time.monotonic()
    monkeypatch.setattr(policy.time, "monotonic", lambda: real + 301)
    with pytest.raises(ValueError):
        policy.execute_dangerous("send_mail", {}, r["confirm_token"], _preview, lambda a: "ok")


def test_token_invalido_rifiutato():
    with pytest.raises(ValueError):
        policy.execute_dangerous("send_mail", {}, "token-inventato", _preview, lambda a: "ok")


def test_errore_esecuzione_propagato_e_auditato():
    r = policy.execute_dangerous(
        "send_mail", {"to": "x@y.it"}, None,
        preview_fn=_preview, execute_fn=lambda a: "ok",
    )

    def boom(a):
        raise RuntimeError("smtp giu")

    with pytest.raises(RuntimeError):
        policy.execute_dangerous("send_mail", {}, r["confirm_token"], _preview, boom)
    entries = _read_audit()
    assert entries[-1]["outcome"] == "error"


def _read_audit():
    with open(policy._audit_path(), encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def test_audit_scritto_e_body_escluso():
    policy.execute_dangerous(
        "send_mail", {"to": "x@y.it", "body": "SEGRETO", "confirm_token": "x"}, None,
        preview_fn=_preview, execute_fn=lambda a: "ok",
    )
    last = _read_audit()[-1]
    assert last["tool"] == "send_mail"
    assert last["outcome"] == "confirmation_requested"
    assert "body" not in last["args"]           # il corpo non finisce nell'audit
    assert "confirm_token" not in last["args"]  # nemmeno i token
