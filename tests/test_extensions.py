"""Il verticale fuori dal core: estensioni spente finche' non si accendono."""
import time

import pytest

from ade_mail_agent.core import appointments, extensions
from ade_mail_agent.core import rules as rules_mod


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.delenv("GIGAMAIL_EXTENSIONS", raising=False)
    rules_mod.set_store(rules_mod.RuleStore(tmp_path / "rules.db"))
    yield rules_mod.store()
    rules_mod.set_store(None)


def test_di_default_nessuna_estensione(store, monkeypatch, tmp_path):
    monkeypatch.setattr("ade_mail_agent.core.data_paths.app_root", lambda: tmp_path)
    assert extensions.enabled_names() == set()
    assert not extensions.enabled("appointments")
    assert extensions.active() == []


def test_chi_usava_gli_appuntamenti_li_ritrova_accesi(store, monkeypatch, tmp_path):
    """Spegnerli in silenzio con l'aggiornamento vorrebbe dire conferme dei
    clienti che non arrivano piu' in agenda."""
    (tmp_path / ".appointments.db").write_bytes(b"")
    monkeypatch.setattr("ade_mail_agent.core.data_paths.app_root", lambda: tmp_path)
    assert extensions.enabled("appointments")
    # la migrazione avviene una volta sola: spenti a mano restano spenti
    extensions.set_enabled("appointments", False)
    assert not extensions.enabled("appointments")


def test_accendere_e_spegnere(store, monkeypatch, tmp_path):
    monkeypatch.setattr("ade_mail_agent.core.data_paths.app_root", lambda: tmp_path)
    extensions.set_enabled("Appointments", True)
    assert extensions.enabled("appointments")
    extensions.set_enabled("appointments", False)
    assert extensions.enabled_names() == set()


def test_la_variabile_d_ambiente_vince(store, monkeypatch):
    extensions.set_enabled("appointments", True)
    monkeypatch.setenv("GIGAMAIL_EXTENSIONS", "")
    assert not extensions.enabled("appointments")


def test_accesa_ma_non_installata_solleva(monkeypatch):
    monkeypatch.setenv("GIGAMAIL_EXTENSIONS", "inesistente")
    with pytest.raises(extensions.ExtensionError):
        extensions.active()


def test_le_builtin_non_si_caricano_come_pacchetti(monkeypatch):
    monkeypatch.setenv("GIGAMAIL_EXTENSIONS", "appointments")
    assert extensions.active() == []


def test_invio_con_appuntamenti_spenti_non_chiama_l_agente(monkeypatch):
    """Il core nudo non manda ogni mail inviata all'agente per cercarci un
    appuntamento, e non segue i thread."""
    from ade_mail_agent.core import mail_router

    chiamate = []
    monkeypatch.setattr(mail_router, "_send_backend", lambda **kw: {"success": True})
    monkeypatch.setattr(mail_router, "_account", lambda aid=None: {"id": 2})
    monkeypatch.setattr(appointments, "segui", lambda *a: chiamate.append(a))
    monkeypatch.setattr(appointments, "dalla_mail_async", lambda *a: chiamate.append(a))
    esito = mail_router.send_message(account_id=2, to="c@example.com",
                                     subject="Visita", body="martedi' alle 10?")
    assert esito == {"success": True}
    assert chiamate == []


def test_watcher_con_appuntamenti_spenti_non_legge_i_thread(monkeypatch):
    from ade_mail_agent import watcher as watcher_mod

    monkeypatch.setattr(appointments, "store",
                        lambda: pytest.fail("store degli appuntamenti aperto"))
    assert watcher_mod.Watcher().sweep_appointments() == 0


def test_cli_enable_chiede_la_verifica(store, monkeypatch, capsys):
    from ade_mail_agent import cli

    monkeypatch.setenv("GIGAMAIL_CONSENT_BACKEND", "deny")
    assert cli.main(["extensions", "enable", "appointments"]) == 1
    assert not extensions.enabled("appointments")
    monkeypatch.setenv("GIGAMAIL_CONSENT_BACKEND", "allow")
    monkeypatch.setenv("ADE_MAIL_DRYRUN", "1")
    assert cli.main(["extensions", "enable", "appointments"]) == 0
    assert extensions.enabled("appointments")
    assert cli.main(["extensions", "disable", "appointments"]) == 0
    assert not extensions.enabled("appointments")


def test_cli_enable_rifiuta_i_nomi_sconosciuti(store, monkeypatch):
    from ade_mail_agent import cli

    monkeypatch.setenv("GIGAMAIL_CONSENT_BACKEND", "allow")
    monkeypatch.setenv("ADE_MAIL_DRYRUN", "1")
    assert cli.main(["extensions", "enable", "boh"]) == 1


# ── il controllo delle bozze nel watcher ────────────────────────────

class _Vieta(extensions.Extension):
    """Respinge le bozze che contengono una parola."""

    def __init__(self, name, parola):
        self.name, self.parola = name, parola

    def draft_constraint(self, subject, body):
        return f"NON SCRIVERE: {self.parola}"

    def check_draft(self, subject, body, draft):
        if self.parola in draft:
            return extensions.DraftCheck(ok=False, detail=f"c'e' {self.parola}",
                                         feedback=f"togli {self.parola}")
        return extensions.DraftCheck(ok=True)


@pytest.fixture()
def mondo(tmp_path, monkeypatch):
    from ade_mail_agent import agent_bridge, policy
    from ade_mail_agent.core import mail_router

    policy.set_store(policy.ApprovalStore(tmp_path / "approvals.db"))
    rules_mod.set_store(rules_mod.RuleStore(tmp_path / "rules.db"))
    stato = {"bozze": [], "prompt": [], "avvisi": []}
    msg = {"id": "1", "subject": "Preventivo", "isRead": False,
           "from": {"emailAddress": {"name": "C", "address": "c@fidato.it"}},
           "body": {"content": "Buongiorno"}}
    monkeypatch.setattr(mail_router, "get_messages", lambda **kw: [msg][kw.get("skip", 0):])
    monkeypatch.setattr(mail_router, "get_message_headers", lambda **kw: {
        "authentication-results": ["mx; dmarc=pass header.from=fidato.it"]})
    monkeypatch.setattr(mail_router, "get_message", lambda **kw: msg)
    monkeypatch.setattr(mail_router, "reply_message", lambda **kw: True)

    def agente(prompt, **kw):
        stato["prompt"].append(prompt)
        return stato["bozze"].pop(0)
    monkeypatch.setattr(agent_bridge, "run", agente)
    monkeypatch.setattr(policy, "notify_approval_requested",
                        lambda *a, **kw: stato["avvisi"].append(kw.get("message", "")))
    rules_mod.store().create(
        account_id=1, trigger_kind="senders", trigger_values=["c@fidato.it"],
        reply_style="cordiale", doc_paths=[], mode="semi", created_by="test",
        hello_verified_at=time.time())
    yield stato
    policy.set_store(None)
    rules_mod.set_store(None)


def _pending():
    from ade_mail_agent import policy
    return policy.store().list_pending()


def test_il_vincolo_entra_nel_prompt(mondo, estensione):
    from ade_mail_agent import watcher as watcher_mod
    estensione(_Vieta("a", "PIPPO"))
    mondo["bozze"] = ["va bene"]
    watcher_mod.Watcher().tick()
    assert "NON SCRIVERE: PIPPO" in mondo["prompt"][0]
    assert len(_pending()) == 1


def test_bozza_respinta_si_riscrive_una_volta(mondo, estensione):
    from ade_mail_agent import watcher as watcher_mod
    estensione(_Vieta("a", "PIPPO"))
    mondo["bozze"] = ["c'e' PIPPO", "pulita"]
    watcher_mod.Watcher().tick()
    assert "togli PIPPO" in mondo["prompt"][1]
    assert [p["args"]["body"] for p in _pending()] == ["pulita"]


def test_la_riscritta_ripassa_da_tutti_i_controlli(mondo, estensione):
    """Corretta per un'estensione, sbagliata per l'altra: non passa."""
    from ade_mail_agent import watcher as watcher_mod
    estensione(_Vieta("a", "PIPPO"))
    estensione(_Vieta("b", "PLUTO"))
    mondo["bozze"] = ["PIPPO", "PLUTO"]
    watcher_mod.Watcher().tick()
    assert _pending() == []
    assert any("b non superato" in a for a in mondo["avvisi"])


def test_estensione_accesa_ma_assente_ferma_la_bozza(mondo, monkeypatch):
    from ade_mail_agent import watcher as watcher_mod
    monkeypatch.setenv("GIGAMAIL_EXTENSIONS", "inesistente")
    mondo["bozze"] = ["x", "x", "x"]
    watcher_mod.Watcher().tick()
    assert _pending() == []
    assert mondo["prompt"] == []   # l'agente non viene nemmeno chiamato
