"""I codici delle unita' (A.3.2, B.1.4) decidono le schede da allegare."""
from gigamail_real_estate import RealEstate

codici = RealEstate().cited_codes


def test_codici_in_ordine_e_senza_ripetizioni():
    testo = ("- A.3.2: quadrilocale di 103,26 mq, prezzo 499.000\n"
             "- B.0.1: quadrilocale di 109,07 mq\n"
             "Le planimetrie di A.3.2 e B.0.1 sono in allegato.")
    assert codici(testo) == ["A.3.2", "B.0.1"]


def test_i_prezzi_non_sono_codici():
    """499.000 e 2028 non devono diventare allegati."""
    assert codici("prezzo 499.000 euro, consegna primavera 2028") == []


def test_nessun_codice_su_testo_qualunque():
    assert codici("Le confermo l'appuntamento.") == []
    assert codici("") == []
