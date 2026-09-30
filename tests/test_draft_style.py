"""La bozza automatica prende dall'observer lo STILE, mai le risposte
vecchie: con quelle davanti l'agente le ricopiava invece di leggere la
mail, perche' le notifiche dei portali hanno oggetti quasi identici."""
import time

import pytest

from ade_mail_agent import policy
from ade_mail_agent import watcher as watcher_mod
from ade_mail_agent.core import rules as rules_mod


@pytest.fixture(autouse=True)
def isolated(tmp_path):
    policy.set_store(policy.ApprovalStore(tmp_path / "approvals.db"))
    rules_mod.set_store(rules_mod.RuleStore(tmp_path / "rules.db"))
    yield
    policy.set_store(None)
    rules_mod.set_store(None)


def _regola():
    return rules_mod.store().create(
        account_id=1, trigger_kind="senders",
        trigger_values=["reply@portale.example"], reply_style="cordiale",
        doc_paths=[], mode="semi", created_by="test",
        hello_verified_at=time.time())


def _msg():
    return {"id": "201", "subject": "Richiesta informazioni",
            "from": {"emailAddress": {"name": "portale",
                                      "address": "reply@portale.example"}},
            "body": {"content": "Buongiorno, vorrei il prezzo."},
            "isRead": False}


def test_gli_esempi_sono_dichiarati_come_stile():
    prompt = watcher_mod.build_draft_prompt(rules_mod.store().get(_regola()), 1, _msg())
    assert "mai al contenuto" in prompt


def test_il_watcher_chiede_allobserver_solo_lo_stile(monkeypatch):
    from ade_mail_agent.core import observer

    chiamate = []
    monkeypatch.setattr(
        observer, "get_context_for_prompt",
        lambda *a, **kw: chiamate.append(kw) or "")
    rule = rules_mod.store().get(_regola())
    watcher_mod.build_draft_prompt(rule, 1, _msg())
    assert chiamate and chiamate[0].get("includi_esempi") is False


def test_observer_senza_esempi_non_restituisce_risposte_vecchie(tmp_path, monkeypatch):
    import sqlite3

    from ade_mail_agent.core import observer

    db = tmp_path / "obs.db"
    monkeypatch.setattr(observer, "DB_PATH", str(db))
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE patterns (account_id INT, pattern_type TEXT,"
                     " pattern_value TEXT, frequency INT)")
        conn.execute("CREATE TABLE interactions (account_id INT, original_draft"
                     " TEXT, final_text TEXT, instruction TEXT, sent_at TEXT)")
        conn.execute("INSERT INTO patterns VALUES (1,'preferred_word','cordialmente',5)")
        conn.execute("INSERT INTO interactions VALUES (1,'x','- B.1.3: trilocale di "
                     "80,43 mq','', '2026-09-27')")
    monkeypatch.setattr(observer, "find_similar_template", lambda *a, **kw: None)
    con = observer.get_context_for_prompt(1, includi_esempi=True)
    senza = observer.get_context_for_prompt(1, includi_esempi=False)
    assert "trilocale" in con
    assert "trilocale" not in senza
    assert "cordialmente" in senza          # lo stile resta

