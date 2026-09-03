# GigaMail — mail for your AI agent
# Copyright (C) 2026 Adecubed
# Licensed under the GNU AGPL v3 or later. See LICENSE.
"""Ritirare un'approvazione data ma non ancora eseguita."""
from ade_mail_agent import policy


def _richiesta():
    res = policy.execute_dangerous(
        "send_mail", {"to": "a@x.it", "subject": "s", "body": "b"}, None,
        preview_fn=lambda: {"to": "a@x.it", "subject": "s"},
        execute_fn=lambda a: None)
    return res["request_id"]


def test_si_revoca_quel_che_e_approvato_ma_non_partito():
    """Il caso vero: si approva, e un secondo dopo ci si accorge che la
    mail era sbagliata. Prima l'unica difesa era aspettare i 15 minuti di
    scadenza, con la richiesta eseguibile per tutta la finestra."""
    rid = _richiesta()
    assert policy.store().approve(rid, by="test")
    assert policy.store().get(rid)["status"] == policy.APPROVED

    assert policy.store().revoke(rid, by="test") is True
    assert policy.store().get(rid)["status"] == policy.REJECTED


def test_una_revoca_impedisce_davvero_l_esecuzione():
    """Non basta cambiare lo stato: dopo la revoca la fase 2 non deve
    trovare piu' nulla da consumare."""
    rid = _richiesta()
    policy.store().approve(rid, by="test")
    policy.store().revoke(rid, by="test")
    assert policy.store().consume_approved(rid, "send_mail") is None


def test_quel_che_e_partito_non_si_annulla():
    """Fingere di annullare una mail gia' inviata sarebbe peggio che
    dire di no: chi legge crederebbe di averla fermata."""
    rid = _richiesta()
    policy.store().approve(rid, by="test")
    assert policy.store().consume_approved(rid, "send_mail") is not None
    assert policy.store().get(rid)["status"] == policy.EXECUTED

    assert policy.store().revoke(rid, by="test") is False
    assert policy.store().get(rid)["status"] == policy.EXECUTED


def test_revoca_ed_esecuzione_insieme_una_sola_vince():
    """Le due strade passano da UPDATE condizionali sullo stesso stato:
    chi arriva secondo deve fallire, non sovrascrivere."""
    rid = _richiesta()
    policy.store().approve(rid, by="test")

    assert policy.store().revoke(rid, by="test") is True
    assert policy.store().consume_approved(rid, "send_mail") is None
    # e una seconda revoca non "ri-revoca"
    assert policy.store().revoke(rid, by="test") is False


def test_revocare_una_pending_equivale_a_rifiutarla():
    rid = _richiesta()
    assert policy.store().revoke(rid, by="test") is True
    assert policy.store().get(rid)["status"] == policy.REJECTED


def test_la_revoca_finisce_nell_audit():
    """Chi ha fermato cosa, e da dove: una decisione che cambia l'esito
    di una mail non puo' essere invisibile."""
    import json
    rid = _richiesta()
    policy.store().approve(rid, by="test")
    policy.store().revoke(rid, by="telegram:123")
    righe = [json.loads(l) for l in
             open(policy._audit_path(), encoding="utf-8") if l.strip()]
    nostre = [r for r in righe
              if r.get("args", {}).get("request_id") == rid
              and r.get("outcome") == "revoked"]
    assert nostre, "la revoca non e' stata auditata"
    assert nostre[-1]["args"]["by"] == "telegram:123"
    assert nostre[-1]["args"]["was"] == policy.APPROVED


def test_l_audit_dice_quale_richiesta():
    """Regressione: audit() toglieva request_id dagli argomenti, quindi una
    riga "approved" non diceva COSA fosse stato approvato — e ricostruire
    chi avesse deciso cosa era impossibile proprio nel log che esiste per
    quello. Il corpo si toglie ancora: e' la mail intera."""
    import json
    rid = _richiesta()
    policy.store().approve(rid, by="test")
    righe = [json.loads(l) for l in
             open(policy._audit_path(), encoding="utf-8") if l.strip()]
    approvate = [r for r in righe
                 if r.get("outcome") == "approved"
                 and r.get("args", {}).get("request_id") == rid]
    assert approvate, "l'approvazione non e' rintracciabile per request_id"
    creazioni = [r for r in righe if r.get("outcome") == "approval_requested"]
    assert creazioni and "body" not in creazioni[-1]["args"]
