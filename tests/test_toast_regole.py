# GigaMail — mail for your AI agent
# Copyright (C) 2026 Adecubed
# Licensed under the GNU AGPL v3 or later. See LICENSE.
"""Le bozze da regola hanno gli stessi bottoni di ogni altra approvazione."""
from ade_mail_agent import policy


def test_la_toast_di_una_regola_ha_anche_modifica():
    """Regressione: la bozza da regola usciva con due soli bottoni,
    Approva e Rifiuta. Su Telegram Modifica c'era, sulla toast no —
    proprio sul canale da cui si approva col PC davanti, e proprio per
    l'azione piu' utile su una bozza scritta da un agente."""
    azioni = policy.toast_actions("req_abc123")
    etichette = [e.split()[-1] for e, _ in azioni]
    assert etichette == ["Leggi", "Approva", "Modifica", "Rifiuta"]
    assert any("edit/req_abc123" in u for _, u in azioni)


def test_le_regole_e_i_tool_usano_la_stessa_funzione():
    """Due elenchi di bottoni scritti a mano in due punti divergono: e'
    esattamente cosi' che Modifica era sparita da un canale solo."""
    import inspect

    from ade_mail_agent.watcher import pipeline
    src = inspect.getsource(pipeline)
    assert "policy.toast_actions(request_id)" in src
    assert "gigamail://approve/{request_id}" not in src


def test_modifica_su_una_bozza_da_regola_la_rifa(monkeypatch):
    """Per una bozza \"Modifica\" significa rifalla cosi': annullarla e
    basta lascerebbe il cliente senza risposta."""
    from ade_mail_agent import cli
    from ade_mail_agent.core import rules as rules_mod

    chiamate = {}

    class _RS:
        def find_by_request(self, rid):
            return {"rule_id": "rule_x", "message_id": "42"}

        def request_retry(self, rule_id, message_id, feedback):
            chiamate["retry"] = (rule_id, message_id, feedback)

    monkeypatch.setattr(rules_mod, "store", lambda: _RS())
    assert cli._retry_di_regola("req_1", "togli i prezzi") is True
    assert chiamate["retry"] == ("rule_x", "42", "togli i prezzi")


def test_modifica_su_una_richiesta_di_un_tool_non_finge(monkeypatch):
    """Senza una regola dietro non c'e' niente da rifare: si annulla e la
    nota torna all'agente, senza promettere una bozza che non arrivera'."""
    from ade_mail_agent import cli
    from ade_mail_agent.core import rules as rules_mod

    class _RS:
        def find_by_request(self, rid):
            return None

    monkeypatch.setattr(rules_mod, "store", lambda: _RS())
    assert cli._retry_di_regola("req_1", "nota") is False


def test_i_bottoni_e_il_gestore_accettano_gli_stessi_id():
    """Il tag della toast accetta id alfanumerici, il gestore dell'URL solo
    esadecimali: un id fuori formato faceva rispondere "URL non
    riconosciuto" a un bottone appena premuto, e l'errore sembrava
    dell'utente. Le due regex devono concordare."""
    import inspect
    import re

    from ade_mail_agent import cli
    from ade_mail_agent.core import desktop_notify as d

    src = inspect.getsource(cli.cmd_open_url)
    regex = re.search(r'r"(\^gigamail://[^"]+)"', src).group(1)
    for rid in ("req_deadbeef", "req_prova9999", "req_A1b2C3"):
        assert re.match(regex, f"gigamail://approve/{rid}"), rid
        assert d._toast_tag([("x", f"gigamail://show/{rid}")]) == rid
    # e resta chiuso a tutto il resto
    assert not re.match(regex, "gigamail://approve/../../etc")
    assert not re.match(regex, "gigamail://elimina/req_abc123")


def test_una_notifica_vecchia_lo_dice(capsys, monkeypatch):
    """Premere una toast rimasta nel centro notifiche dopo che la sua
    richiesta e' sparita rispondeva "inesistente": sembra un guasto del
    programma invece di "questa e' vecchia, non devi fare niente". Dire
    quante richieste ci sono davvero in attesa chiude la domanda."""
    from ade_mail_agent import cli, policy

    class _Store:
        def list_pending(self):
            return []

    monkeypatch.setattr(policy, "store", lambda: _Store())
    cli._spiega_richiesta_assente("req_sparita")
    out = capsys.readouterr().out
    assert "vecchia" in out
    assert "non devi fare nulla" in out


def test_se_invece_c_e_qualcosa_in_attesa_lo_elenca(capsys, monkeypatch):
    from ade_mail_agent import cli, policy

    class _Store:
        def list_pending(self):
            return [{"request_id": "req_viva", "tool": "send_mail",
                     "preview": {"to": "cliente@x.it"}}]

    monkeypatch.setattr(policy, "store", lambda: _Store())
    cli._spiega_richiesta_assente("req_sparita")
    out = capsys.readouterr().out
    assert "In attesa adesso: 1" in out
    assert "req_viva" in out and "cliente@x.it" in out


def test_la_finestra_non_muore_senza_input(monkeypatch):
    """La finestra aperta da una toast si chiude con INVIO. Senza stdin
    finiva con un traceback: l'ultima cosa che l'utente vede sarebbe un
    errore che non lo riguarda."""
    from ade_mail_agent import cli

    def _boom(_):
        raise EOFError

    monkeypatch.setattr("builtins.input", _boom)
    cli._attendi_invio()      # non deve sollevare
