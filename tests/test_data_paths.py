"""Coerenza dei percorsi dati: TUTTI i moduli devono concordare.

Storia: sei moduli leggevano APPDATA per conto proprio, ognuno col suo
fallback. Lanciato da un client MCP che filtra l'ambiente (Hermes passa
solo un baseline di variabili, senza APPDATA) il server apriva un
.accounts.db vuoto e creava approvazioni in un DB che console e CLI non
leggevano mai: fallimento silenzioso del gate di approvazione.
Ora data_paths.py e' l'unica fonte; questi test impediscono la ricaduta.
"""
import importlib

from ade_mail_agent.core import data_paths


def test_data_root_sotto_app_root():
    assert data_paths.data_root() == data_paths.app_root() / "mail"


def test_ade_root_sposta_tutto(monkeypatch, tmp_path):
    """ADE_ROOT deve redirigere approvazioni E dati mail insieme."""
    monkeypatch.setenv("ADE_ROOT", str(tmp_path / "altrove"))
    monkeypatch.delenv("ADE_MAIL_DATA_DIR", raising=False)
    assert data_paths.app_root() == tmp_path / "altrove"
    assert data_paths.data_root() == tmp_path / "altrove" / "mail"


def test_ade_mail_data_dir_sposta_solo_mail(monkeypatch, tmp_path):
    monkeypatch.setenv("ADE_MAIL_DATA_DIR", str(tmp_path / "solomail"))
    assert data_paths.data_root() == tmp_path / "solomail"
    # app_root non deve seguire l'override dei dati mail
    assert data_paths.app_root() != tmp_path / "solomail"


def test_senza_appdata_percorso_unico(monkeypatch, tmp_path):
    """Senza APPDATA (client MCP che filtra l'ambiente) il fallback e' UNO,
    non due: era ~/ADE per cinque moduli e ~/.ade per data_paths."""
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.delenv("ADE_ROOT", raising=False)
    monkeypatch.delenv("ADE_MAIL_DATA_DIR", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))  # Path.home() su Windows
    assert data_paths.app_root() == tmp_path / ".ade"
    assert data_paths.data_root() == tmp_path / ".ade" / "mail"


def test_gigamail_root_nuovo_nome(monkeypatch, tmp_path):
    monkeypatch.delenv("ADE_ROOT", raising=False)
    monkeypatch.delenv("ADE_MAIL_DATA_DIR", raising=False)
    monkeypatch.delenv("GIGAMAIL_DATA_DIR", raising=False)
    monkeypatch.setenv("GIGAMAIL_ROOT", str(tmp_path / "nuovo"))
    assert data_paths.app_root() == tmp_path / "nuovo"
    assert data_paths.data_root() == tmp_path / "nuovo" / "mail"


def test_alias_ade_root_funziona_ancora(monkeypatch, tmp_path):
    """Config esistenti (INTEGRATIONS.md 0.1.3, skill ClawHub, manifest
    Hermes) usano ADE_ROOT: non si rompono."""
    monkeypatch.delenv("GIGAMAIL_ROOT", raising=False)
    monkeypatch.setenv("ADE_ROOT", str(tmp_path / "legacy"))
    assert data_paths.app_root() == tmp_path / "legacy"


def test_nuovo_nome_vince_sull_alias(monkeypatch, tmp_path):
    monkeypatch.setenv("GIGAMAIL_ROOT", str(tmp_path / "nuovo"))
    monkeypatch.setenv("ADE_ROOT", str(tmp_path / "legacy"))
    assert data_paths.app_root() == tmp_path / "nuovo"


def test_moduli_concordano_sui_percorsi():
    """I DB calcolati a import-time dai moduli core devono stare tutti
    sotto data_root(): nessun modulo calcola i percorsi per conto suo."""
    from ade_mail_agent.core import accounts, observer, mail_memory, ade_masker
    from ade_mail_agent import policy

    root = str(data_paths.data_root())
    assert accounts._ADE_DATA == root
    assert observer.DB_PATH.startswith(root)
    assert mail_memory._DB_PATH.startswith(root)
    assert ade_masker._db_path().startswith(root)
    # le approvazioni vivono in app_root, un livello sopra
    assert str(policy._ade_root()) == str(data_paths.app_root())
