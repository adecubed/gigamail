"""B3: la preview mostra indirizzi, mai display name, e avvisa quando un
destinatario non e' un indirizzo esplicito (gruppo/alias: puo' espandersi).
B5: notifica pluggable alla creazione della richiesta — solo notifica,
senza shell, best-effort, mai bloccante.
"""
import json
import os
import sys
import time

import pytest

from ade_mail_agent import policy


@pytest.fixture(autouse=True)
def store_isolato(tmp_path):
    policy.set_store(policy.ApprovalStore(tmp_path / "approvals.db"))
    yield
    policy.set_store(None)


# ------------------------------------------------------------------- B3

def test_display_name_ridotto_a_indirizzo():
    d = policy.describe_recipients("Mario Rossi <mario@x.it>")
    assert d["recipients"][0]["address"] == "mario@x.it"
    assert d["recipients"][0]["explicit"] is True
    assert "warning" not in d


def test_nome_nudo_o_gruppo_segnalato():
    d = policy.describe_recipients("Team Vendite", cc=["b@x.it"])
    r = {x["address"]: x for x in d["recipients"]}
    assert r["Team Vendite"]["may_expand"] is True
    assert r["b@x.it"]["explicit"] is True
    assert d["count"] == 2
    assert "Team Vendite" in d["warning"] and "not guaranteed" in d["warning"]


def test_lista_separata_da_virgole_e_punto_e_virgola():
    d = policy.describe_recipients("a@x.it, b@x.it; Gruppo")
    assert d["count"] == 3
    assert [x["field"] for x in d["recipients"]] == ["to", "to", "to"]


def test_preview_send_mail_contiene_recipients():
    """Il tool send_mail del server mette describe_recipients nella preview."""
    from ade_mail_agent import server
    out = server.send_mail.fn(to="Cliente <c@x.it>", subject="s", body="b",
                              cc=["Lista Clienti"]) if hasattr(server.send_mail, "fn") \
        else server.send_mail(to="Cliente <c@x.it>", subject="s", body="b", cc=["Lista Clienti"])
    prev = out["preview"]
    assert prev["count"] == 2
    addrs = {x["address"] for x in prev["recipients"]}
    assert addrs == {"c@x.it", "Lista Clienti"}
    assert "Lista Clienti" in prev["warning"]


# ------------------------------------------------------------------- B5

def _phase1():
    return policy.execute_dangerous(
        "send_mail", {"to": "a@x.it", "subject": "s", "body": "b"}, None,
        preview_fn=lambda: {"to": "a@x.it", "subject": "s"}, execute_fn=lambda a: None)


def _wait_for(path, timeout=5.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if os.path.exists(path) and os.path.getsize(path) > 0:
            return True
        time.sleep(0.05)
    return False


def test_senza_config_nessuna_notifica(monkeypatch):
    monkeypatch.delenv("GIGAMAIL_APPROVAL_NOTIFY_CMD", raising=False)
    assert policy.notify_approval_requested("req_x", "send_mail", {}) is False


def test_notifica_eseguita_con_placeholder(monkeypatch, tmp_path):
    out = tmp_path / "notified.txt"
    cmd = [sys.executable, "-c",
           "import sys; open(sys.argv[1],'w',encoding='utf-8').write(' | '.join(sys.argv[2:]))",
           str(out), "{request_id}", "{tool}", "{summary}"]
    monkeypatch.setenv("GIGAMAIL_APPROVAL_NOTIFY_CMD", json.dumps(cmd))
    r = _phase1()
    assert _wait_for(out)
    text = out.read_text(encoding="utf-8")
    assert r["request_id"] in text and "send_mail" in text and "to=a@x.it" in text


def test_summary_non_e_interpretato_come_comando(monkeypatch, tmp_path):
    """Preview ostile: il testo arriva al comando come ARGOMENTO, non viene
    mai passato a una shell."""
    out = tmp_path / "args.txt"
    cmd = [sys.executable, "-c",
           "import sys; open(sys.argv[1],'w',encoding='utf-8').write(repr(sys.argv[2]))",
           str(out), "{summary}"]
    monkeypatch.setenv("GIGAMAIL_APPROVAL_NOTIFY_CMD", json.dumps(cmd))
    hostile = "x; rm -rf / $(touch /tmp/pwned) `id` && echo pwn"
    policy.notify_approval_requested("req_h", "send_mail", {"subject": hostile})
    assert _wait_for(out)
    assert hostile in out.read_text(encoding="utf-8")


def test_comando_inesistente_non_rompe_la_fase1(monkeypatch):
    monkeypatch.setenv("GIGAMAIL_APPROVAL_NOTIFY_CMD",
                       json.dumps(["/nonexistent/binary-xyz", "{request_id}"]))
    r = _phase1()
    assert r["status"] == "approval_required" and r["request_id"]


def test_config_malformata_ignorata(monkeypatch):
    monkeypatch.setenv("GIGAMAIL_APPROVAL_NOTIFY_CMD", "not json at all")
    assert policy._notify_command() is None
    monkeypatch.setenv("GIGAMAIL_APPROVAL_NOTIFY_CMD", json.dumps("una stringa"))
    assert policy._notify_command() is None
    monkeypatch.setenv("GIGAMAIL_APPROVAL_NOTIFY_CMD", json.dumps([]))
    assert policy._notify_command() is None


def test_dedup_non_rinotifica(monkeypatch, tmp_path):
    """La seconda richiesta identica (dedup) NON lancia una seconda
    notifica: l'umano ne riceve una per richiesta, non una per retry."""
    counter = tmp_path / "count.txt"
    cmd = [sys.executable, "-c",
           "import sys; open(sys.argv[1],'a').write('x')", str(counter)]
    monkeypatch.setenv("GIGAMAIL_APPROVAL_NOTIFY_CMD", json.dumps(cmd))
    _phase1()
    _phase1()
    _phase1()
    assert _wait_for(counter)
    time.sleep(0.5)
    assert counter.read_text() == "x"


def test_placeholder_message_porta_il_testo_completo(monkeypatch, tmp_path):
    """{message} = testo leggibile per l'umano ("e' arrivata una mail da...,
    propongo..., approvi?"), passato dal watcher; senza message esplicito
    degrada al riassunto."""
    out = tmp_path / "msg.txt"
    cmd = [sys.executable, "-c",
           "import sys; open(sys.argv[1],'w',encoding='utf-8').write(sys.argv[2])",
           str(out), "{message}"]
    monkeypatch.setenv("GIGAMAIL_APPROVAL_NOTIFY_CMD", json.dumps(cmd))
    testo = "E' arrivata una mail da x@y.it. Propongo: ciao. Approvi?"
    policy.notify_approval_requested("req_m", "reply_mail", {"subject": "s"},
                                     message=testo)
    assert _wait_for(out)
    assert out.read_text(encoding="utf-8") == testo


def test_comando_da_notify_json_se_manca_env(monkeypatch, tmp_path):
    """Il comando puo' vivere in notify.json accanto ad agent.json: la
    configurazione sopravvive senza env var. L'env, se c'e', vince."""
    monkeypatch.delenv("GIGAMAIL_APPROVAL_NOTIFY_CMD", raising=False)
    cfg = policy._ade_root() / "notify.json"
    cfg.write_text(json.dumps({"command": ["mycmd", "{message}"]}),
                   encoding="utf-8")
    try:
        assert policy._notify_command() == ["mycmd", "{message}"]
        monkeypatch.setenv("GIGAMAIL_APPROVAL_NOTIFY_CMD",
                           json.dumps(["envcmd", "{summary}"]))
        assert policy._notify_command() == ["envcmd", "{summary}"]
        # file malformato: ignorato, nessuna eccezione
        monkeypatch.delenv("GIGAMAIL_APPROVAL_NOTIFY_CMD", raising=False)
        cfg.write_text("garbage", encoding="utf-8")
        assert policy._notify_command() is None
    finally:
        cfg.unlink(missing_ok=True)


def test_desktop_notify_spento_via_env(monkeypatch):
    from ade_mail_agent.core import desktop_notify
    monkeypatch.setenv("GIGAMAIL_NOTIFY_DESKTOP", "0")
    assert desktop_notify.enabled() is False
    assert desktop_notify.notify("t", "b", background=False) is False


def test_notifica_non_approva_niente(monkeypatch, tmp_path):
    """Il comando di notifica gira; la richiesta resta PENDING.
    La notifica e' un avviso, non un canale di approvazione."""
    monkeypatch.setenv("GIGAMAIL_APPROVAL_NOTIFY_CMD",
                       json.dumps([sys.executable, "-c", "pass"]))
    r = _phase1()
    time.sleep(0.3)
    assert policy.store().get(r["request_id"])["status"] == policy.PENDING
