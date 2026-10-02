"""I codici delle unita' (A.9.2, B.7.4) decidono le schede da allegare."""
from gigamail_real_estate import RealEstate

codici = RealEstate().cited_codes


def test_codici_in_ordine_e_senza_ripetizioni():
    testo = ("- A.9.2: quadrilocale di 100,00 mq, prezzo 450.000\n"
             "- B.6.1: quadrilocale di 105,00 mq\n"
             "Le planimetrie di A.9.2 e B.6.1 sono in allegato.")
    assert codici(testo) == ["A.9.2", "B.6.1"]


def test_i_prezzi_non_sono_codici():
    """450.000 e 2028 non devono diventare allegati."""
    assert codici("prezzo 450.000 euro, consegna primavera 2028") == []


def test_nessun_codice_su_testo_qualunque():
    assert codici("Le confermo l'appuntamento.") == []
    assert codici("") == []
