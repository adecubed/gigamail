"""PIN locale: il consenso umano dove non c'e' Windows Hello ne' Touch ID.

Piu' debole di Hello, ma chiude il caso normale: un agente che lancia
`gigamail approvals approve` da uno script non ha un terminale, e senza
il PIN non passa."""
import getpass

import pytest

from gigamail import consent
from gigamail.core import approval_pin
from gigamail.core import rules as rules_mod

PIN = "482915"


@pytest.fixture(autouse=True)
def linux(tmp_path, monkeypatch):
    monkeypatch.delenv("GIGAMAIL_CONSENT_BACKEND", raising=False)
    monkeypatch.setattr(consent, "_WIN", False)
    monkeypatch.setattr(consent, "_MAC", False)
    rules_mod.set_store(rules_mod.RuleStore(tmp_path / "rules.db"))
    yield
    rules_mod.set_store(None)


def _con_pin():
    consent.set_local_pin(approval_pin.hash_pin(PIN))


def _terminale(monkeypatch, si=True):
    monkeypatch.setattr(consent, "_terminale", lambda: si)


def _digita(monkeypatch, *valori):
    it = iter(valori)
    monkeypatch.setattr(getpass, "getpass", lambda *a, **k: next(it))


def test_senza_pin_nessun_backend_e_il_messaggio_dice_come(monkeypatch):
    _terminale(monkeypatch)
    assert consent.backend_name() is None
    with pytest.raises(consent.ConsentUnavailable, match="approvals pin"):
        consent.require_human("prova")


def test_senza_terminale_il_pin_non_si_chiede(monkeypatch):
    """L'agente che lancia il comando da uno script."""
    _con_pin()
    _terminale(monkeypatch, False)
    assert consent.backend_name() is None
    with pytest.raises(consent.ConsentUnavailable, match="terminale"):
        consent.require_human("prova")


def test_pin_giusto_approva(monkeypatch):
    _con_pin()
    _terminale(monkeypatch)
    _digita(monkeypatch, PIN)
    assert consent.backend_name() == "terminal-pin"
    assert consent.require_human("prova") is True


def test_tre_errori_bloccano_anche_il_pin_giusto(monkeypatch):
    _con_pin()
    _terminale(monkeypatch)
    _digita(monkeypatch, "000001", "000002", "000003", PIN)
    for _ in range(3):
        assert consent.require_human("prova") is False
    assert consent.local_pin_locked() > 0
    assert consent.require_human("prova") is False
    assert "bloccato" in consent.last_reason()


def test_su_windows_e_mac_il_pin_non_vale(monkeypatch):
    _con_pin()
    _terminale(monkeypatch)
    monkeypatch.setattr(consent, "_WIN", True)
    monkeypatch.setattr(consent, "_win_available", lambda: False)
    assert consent.backend_name() is None


def test_cli_imposta_e_cambia_solo_col_pin_attuale(monkeypatch):
    from gigamail import cli
    _terminale(monkeypatch)
    _digita(monkeypatch, PIN, PIN)
    assert cli.main(["approvals", "pin"]) == 0
    assert consent.local_pin_set()
    _digita(monkeypatch, "999999")            # PIN attuale sbagliato
    assert cli.main(["approvals", "pin", "--remove"]) == 1
    assert consent.local_pin_set()
    _digita(monkeypatch, PIN)
    assert cli.main(["approvals", "pin", "--remove"]) == 0
    assert not consent.local_pin_set()


def test_cli_pin_senza_terminale_rifiuta(monkeypatch):
    from gigamail import cli
    _terminale(monkeypatch, False)
    assert cli.main(["approvals", "pin"]) == 2
    assert not consent.local_pin_set()
