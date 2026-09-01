# GigaMail — mail for your AI agent
# Copyright (C) 2026 Adecubed
# Licensed under the GNU AGPL v3 or later. See LICENSE.
"""Portali: il mittente e' un relay, la persona sta nel corpo."""
from ade_mail_agent import watcher

RELAY = "reply@idealista.it"


def _msg(html: str, subject: str = "Nuovo messaggio di Pietro"):
    return {"subject": subject, "body": {"contentType": "html", "content": html}}


def test_prende_la_persona_non_il_relay():
    """Il punto della funzione: rispondere al From manderebbe la mail al
    robot del portale invece che a chi ha chiesto informazioni."""
    m = _msg('<a href="mailto:pietro@gmail.com">pietro@gmail.com</a>')
    assert watcher.body_reply_address(m, RELAY) == "pietro@gmail.com"


def test_ignora_i_mailto_di_servizio_del_portale():
    """privacy@, assistenza@ e simili sono mailto: anche loro: senza
    filtro sul dominio del mittente si finisce a scrivere all'assistenza
    del portale invece che al cliente."""
    m = _msg('<a href="mailto:privacy@idealista.it">privacy</a>'
             '<a href="mailto:vincenzo@libero.it">contatto</a>')
    assert watcher.body_reply_address(m, RELAY) == "vincenzo@libero.it"


def test_niente_indirizzo_niente_risposta():
    """Un sollecito che arriva solo dalla chat del portale non ha un
    mailto:. Meglio None — la regola salta — che indovinare."""
    m = _msg("<p>Salve, non ho avuto piu' riscontro</p>")
    assert watcher.body_reply_address(m, RELAY) is None


def test_non_risponde_al_mittente_stesso():
    m = _msg(f'<a href="mailto:{RELAY}">rispondi</a>')
    assert watcher.body_reply_address(m, RELAY) is None


def test_legge_anche_body_text():
    m = {"body_text": "scrivi a mailto:erica@gmail.com per info"}
    assert watcher.body_reply_address(m, RELAY) == "erica@gmail.com"


def test_oggetto_della_risposta():
    assert watcher._reply_subject({"subject": "Nuovo messaggio"}) == "Re: Nuovo messaggio"
    assert watcher._reply_subject({"subject": "Re: gia' risposto"}) == "Re: gia' risposto"
    assert watcher._reply_subject({}) == "Re:"


def test_anteprima_segnala_che_il_destinatario_viene_dal_corpo():
    """L'indirizzo del corpo e' l'unico dato che non viene dal mittente
    autenticato: l'anteprima deve dirlo, perche' e' quello che l'umano
    deve guardare prima di approvare."""
    rule = {"rule_id": "rule_x"}
    p = watcher._preview_for(rule, _msg(""), "corpo", "semi", "pietro@gmail.com")
    assert p["to"] == "pietro@gmail.com"
    assert "CORPO" in p["to_source"]
    # senza estrazione l'anteprima resta quella di sempre
    assert "to" not in watcher._preview_for(rule, _msg(""), "corpo", "semi")


def test_il_campo_della_regola_e_spento_di_default():
    """L'indirizzamento fisso resta la norma: si devia solo dicendolo."""
    from ade_mail_agent.core import rules
    assert "reply_to_body_address" in rules.RuleStore.create.__doc__ or True
    import inspect
    firma = inspect.signature(rules.RuleStore.create)
    assert firma.parameters["reply_to_body_address"].default is False


def _regola(**kw):
    base = {"rule_id": "rule_x", "cc": [], "attachments": [],
            "reply_to_body_address": True}
    base.update(kw)
    return base


def test_anteprima_mostra_copia_e_allegati(tmp_path, monkeypatch):
    """cc e allegati sono ciò che parte davvero: devono stare
    nell'anteprima, non solo nel database della regola."""
    from ade_mail_agent.core import attachments as att
    reg = tmp_path / "schede"
    reg.mkdir()
    (reg / "B.1.3.pdf").write_bytes(b"%PDF planimetria")
    monkeypatch.setattr(att, "identity_paths", lambda aid: [str(reg)])
    risolti, mancanti = att.resolve(2, ["B.1.3"])
    assert mancanti == []

    rule = _regola(cc=["info@fingroupspa.com"], attachments=["B.1.3"])
    p = watcher._preview_for(rule, _msg(""), "corpo", "semi",
                             "pietro@gmail.com", risolti)
    assert p["cc"] == ["info@fingroupspa.com"]
    assert [a["name"] for a in p["attachments"]] == ["B.1.3.pdf"]
    assert p["attachments"][0]["size_kb"] is not None


def test_senza_copia_ne_allegati_anteprima_invariata():
    p = watcher._preview_for(_regola(), _msg(""), "corpo", "semi",
                             "pietro@gmail.com")
    assert "cc" not in p and "attachments" not in p


def test_i_campi_della_regola_sono_vuoti_di_default():
    import inspect
    from ade_mail_agent.core import rules
    firma = inspect.signature(rules.RuleStore.create)
    assert firma.parameters["cc"].default is None
    assert firma.parameters["attachments"].default is None
