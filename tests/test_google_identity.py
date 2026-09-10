"""Identita' Google: storage cifrato, scelta del calendario, Drive.

Il punto delicato non e' il salvataggio, e' la regola di scelta del
provider: collegare Google per Drive NON deve spostare il calendario di
chi usa Microsoft da anni. Quel comportamento e' verificato qui perche'
una regressione sarebbe silenziosa.
"""

import sqlite3

import pytest

from ade_mail_agent.core import accounts, calendar_router, google_drive


@pytest.fixture(autouse=True)
def db_pulito():
    """Ogni test parte senza identita' Google ne' scelta di provider."""
    def svuota():
        with sqlite3.connect(accounts.DB_PATH) as conn:
            conn.execute("DELETE FROM google_identity")
            conn.execute("DELETE FROM app_setting WHERE key='calendar_provider'")
            conn.execute("DELETE FROM accounts")
            conn.commit()
    svuota()
    yield
    svuota()


# -- storage ------------------------------------------------------------------

def test_salva_e_rilegge_il_refresh_token():
    accounts.save_google_identity("Mario@Example.com", "Mario",
                                  {"refresh_token": "rt-segreto"})
    ident = accounts.get_google_identity()
    assert ident["email"] == "mario@example.com", "l'email va normalizzata"
    assert ident["data"]["refresh_token"] == "rt-segreto"


def test_il_refresh_token_non_e_in_chiaro_nel_db():
    accounts.save_google_identity("mario@example.com", "Mario",
                                  {"refresh_token": "rt-segreto"})
    with sqlite3.connect(accounts.DB_PATH) as conn:
        grezzo = conn.execute("SELECT data_enc FROM google_identity").fetchone()[0]
    assert "rt-segreto" not in grezzo


def test_la_lista_non_espone_segreti():
    accounts.save_google_identity("mario@example.com", "Mario",
                                  {"refresh_token": "rt-segreto"})
    righe = accounts.list_google_identities()
    assert len(righe) == 1
    assert "data" not in righe[0] and "data_enc" not in righe[0]


def test_secondo_login_aggiorna_invece_di_duplicare():
    accounts.save_google_identity("mario@example.com", "Mario", {"refresh_token": "v1"})
    accounts.save_google_identity("MARIO@example.com", "Mario R", {"refresh_token": "v2"})
    righe = accounts.list_google_identities()
    assert len(righe) == 1
    assert accounts.get_google_identity()["data"]["refresh_token"] == "v2"


def test_logout_cancella_l_identita():
    accounts.save_google_identity("mario@example.com", "Mario", {"refresh_token": "rt"})
    assert accounts.delete_google_identity("mario@example.com") is True
    assert accounts.get_google_identity() is None


# -- scelta del provider ------------------------------------------------------

def _account_microsoft():
    accounts.add_microsoft_account("MS", "mario@fingroup.it", "{}")


def test_senza_google_il_calendario_resta_microsoft():
    _account_microsoft()
    assert calendar_router.provider() == "microsoft"


def test_collegare_google_non_sposta_un_calendario_microsoft():
    """La regressione da evitare: collego Drive e perdo gli appuntamenti."""
    _account_microsoft()
    accounts.save_google_identity("mario@example.com", "Mario", {"refresh_token": "rt"})
    assert calendar_router.provider() == "microsoft"


def test_solo_google_configurato_usa_google():
    accounts.save_google_identity("mario@example.com", "Mario", {"refresh_token": "rt"})
    assert calendar_router.provider() == "google"


def test_scelta_esplicita_vince_su_tutto():
    _account_microsoft()
    accounts.save_google_identity("mario@example.com", "Mario", {"refresh_token": "rt"})
    accounts.set_calendar_provider("google")
    assert calendar_router.provider() == "google"
    accounts.set_calendar_provider("microsoft")
    assert calendar_router.provider() == "microsoft"


def test_provider_sconosciuto_rifiutato():
    with pytest.raises(ValueError):
        accounts.set_calendar_provider("yahoo")


# -- Drive: input non fidato --------------------------------------------------

def test_nome_da_drive_non_puo_scrivere_fuori_cartella():
    """Il nome del file arriva da Drive, quindi da fuori: un percorso
    dentro il nome non deve diventare un percorso vero."""
    assert google_drive._nome_sicuro("../../.ssh/authorized_keys") == "authorized_keys"
    assert google_drive._nome_sicuro(r"..\..\windows\system32\a.dll") == "a.dll"
    assert google_drive._nome_sicuro("rela:zione?.pdf") == "rela_zione_.pdf"
    assert google_drive._nome_sicuro("   ") == "file"
