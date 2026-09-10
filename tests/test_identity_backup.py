# GigaMail — mail for your AI agent
# Copyright (C) 2026 Adecubed
# Licensed under the GNU AGPL v3 or later. See LICENSE.
"""Storia locale dell'identity: copie sul computer, mai nel repository."""
import json

from ade_mail_agent.core import identity_backup as ib

IDENTITA = {
    "who_am_i": "Ufficio vendite",
    "what_i_do": "vendo appartamenti",
    "tone": "cordiale",
    "key_info": "consegna primavera 2028",
    "file_paths": [r"C:\listini\prezzi.xlsx"],
}


def test_salva_solo_i_campi_dell_identity(tmp_path):
    """I campi si elencano uno per uno invece di copiare la riga intera:
    se un domani la tabella ne guadagnasse uno — poniamo una credenziale —
    non finirebbe nella copia per inerzia."""
    # valori finti: servono solo a provare che NON finiscano nella copia
    fuori = {"password": "pw", "imap_host": "mail.x.it"}
    identita = {**IDENTITA, **fuori}
    p = ib.snapshot(1, identita, root=str(tmp_path))
    salvato = json.loads(open(p, encoding="utf-8").read())
    assert set(salvato["identity"]) == set(ib.CAMPI)
    testo = json.dumps(salvato).lower()
    assert all(v not in testo for v in fuori.values())
    assert "password" not in testo


def test_una_copia_per_cambiamento_non_per_avvio(tmp_path):
    """Senza questo controllo ogni riavvio del watcher riempirebbe la
    cartella di file identici, e la storia diventerebbe illeggibile
    proprio quando serve."""
    assert ib.snapshot(1, IDENTITA, root=str(tmp_path))
    assert ib.snapshot(1, IDENTITA, root=str(tmp_path)) is None
    cambiata = dict(IDENTITA, key_info="consegna primavera 2028; niente visite")
    assert ib.snapshot(1, cambiata, root=str(tmp_path))
    assert len(ib.storia(1, root=str(tmp_path))) == 2


def test_la_storia_e_in_ordine_e_per_account(tmp_path):
    ib.snapshot(1, IDENTITA, root=str(tmp_path))
    ib.snapshot(2, dict(IDENTITA, key_info="altro account"), root=str(tmp_path))
    ib.snapshot(1, dict(IDENTITA, key_info="secondo giro"), root=str(tmp_path))
    uno = ib.storia(1, root=str(tmp_path))
    assert len(uno) == 2
    assert ib.leggi(uno[-1])["identity"]["key_info"] == "secondo giro"
    assert len(ib.storia(2, root=str(tmp_path))) == 1
    assert ib.storia(99, root=str(tmp_path)) == []


def test_scrivere_l_identity_salva_la_versione_precedente(tmp_path, monkeypatch):
    """Il momento della sovrascrittura e' l'unico in cui la versione
    precedente esiste ancora: se la copia non parte di li', la storia
    dipende dal ricordarsi di un comando."""
    from ade_mail_agent.core import accounts

    monkeypatch.setattr(ib, "cartella", lambda root=None: str(tmp_path))
    accounts.set_identity(7, who_am_i="prima", key_info="regola uno")
    accounts.set_identity(7, who_am_i="prima", key_info="regola uno e due")

    copie = ib.storia(7, root=str(tmp_path))
    assert copie, "nessuna copia: la storia non si sta formando"
    testi = [ib.leggi(p)["identity"]["key_info"] for p in copie]
    assert "regola uno" in testi, testi
    assert accounts.get_identity(7)["key_info"] == "regola uno e due"


def test_una_copia_che_fallisce_non_blocca_la_modifica(monkeypatch):
    """La copia e' un servizio, non un cancello: se la cartella non e'
    scrivibile l'identity si deve poter cambiare lo stesso."""
    from ade_mail_agent.core import accounts

    def _rotto(*a, **k):
        raise OSError("disco pieno")

    monkeypatch.setattr(ib, "snapshot", _rotto)
    accounts.set_identity(8, key_info="passa comunque")
    assert accounts.get_identity(8)["key_info"] == "passa comunque"


def test_pota_tiene_le_piu_recenti(tmp_path):
    for n in range(5):
        ib.snapshot(1, dict(IDENTITA, key_info=f"versione {n}"), root=str(tmp_path))
    assert ib.pota(1, tieni=2, root=str(tmp_path)) == 3
    resta = ib.storia(1, root=str(tmp_path))
    assert len(resta) == 2
    assert ib.leggi(resta[-1])["identity"]["key_info"] == "versione 4"
