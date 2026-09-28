"""L'archivio: ogni mail salvata per intero, cercabile e leggibile anche
quando il server non ce l'ha piu'.

28/09/2026: una bolletta arrivata a gennaio esisteva solo nel file di
Outlook, che dopo due settimane la toglie dal server. GigaMail leggeva
solo il server e rispondeva "nessun risultato".
"""
import email.utils
from email.message import EmailMessage

import pytest

from ade_mail_agent.core import archivio, archivio_sync, outlook_import


def _mime(mid="<abc@mediocasa>", da="Mediocasa <info@mediocasaimmobiliare.eu>",
          a="conti@fingroupspa.com", cc="luca.ferri@example.org",
          oggetto="Utenze e Iban Mediocasa - immobile in Seveso",
          corpo="Allego le ultime due bollette della proprietà di gas e luce.",
          allegato=("EE00105559_2026_2026.pdf", b"%PDF-1.4 bolletta luce"),
          data="Wed, 28 Jan 2026 15:13:00 +0100") -> bytes:
    m = EmailMessage()
    if mid:
        m["Message-ID"] = mid
    m["From"], m["To"], m["Subject"], m["Date"] = da, a, oggetto, data
    if cc:
        m["Cc"] = cc
    m.set_content(corpo)
    if allegato:
        m.add_attachment(allegato[1], maintype="application", subtype="pdf",
                         filename=allegato[0])
    return m.as_bytes()


@pytest.fixture()
def st(tmp_path):
    s = archivio.ArchiveStore(tmp_path / "a.db", tmp_path / "mail")
    archivio.set_store(s)
    yield s
    archivio.set_store(None)


# ── salvare e cercare ────────────────────────────────────────────────

def test_la_ricerca_trova_il_dominio_per_prefisso(st):
    st.salva(1, _mime())
    trovate = st.cerca(1, "mediocasa")
    assert len(trovate) == 1
    assert trovate[0]["subject"].startswith("Utenze e Iban")
    assert trovate[0]["id"].startswith(archivio.PREFISSO_ID)


def test_la_ricerca_guarda_cc_testo_e_nomi_degli_allegati(st):
    st.salva(1, _mime())
    assert st.cerca(1, "ferri")                 # in copia
    assert st.cerca(1, "bollette")                  # nel testo
    assert st.cerca(1, "EE00105559")                # nel nome dell'allegato
    assert st.cerca(1, "proprieta")                 # senza accento
    assert not st.cerca(2, "mediocasa")             # altro account


def test_stessa_mail_due_volte_resta_una_riga(st):
    _id1, nuovo1 = st.salva(1, _mime(), folder="INBOX", provider_id="10")
    _id2, nuovo2 = st.salva(1, _mime(), folder="INBOX.idealista", provider_id="3")
    assert nuovo1 and not nuovo2 and _id1 == _id2
    riga = st.riga(1, f"{archivio.PREFISSO_ID}{_id1}")
    assert riga["folder"] == "INBOX.idealista" and riga["provider_id"] == "3"


def test_la_copia_del_server_vince_su_quella_di_outlook(st):
    _id, _ = st.salva(1, _mime(corpo="ricostruita"), source="outlook")
    st.salva(1, _mime(corpo="originale dal server"), source="imap")
    assert st.riga(1, f"{archivio.PREFISSO_ID}{_id}")["source"] == "imap"
    assert st.cerca(1, "originale")


def test_senza_message_id_la_chiave_e_il_contenuto(st):
    st.salva(1, _mime(mid=None))
    st.salva(1, _mime(mid=None))
    assert sum(st.conta(1).values()) == 1


# ── leggere dall'archivio ───────────────────────────────────────────

def test_lettura_e_allegato_dallarchivio(st):
    _id, _ = st.salva(1, _mime(), folder="INBOX", provider_id="10")
    m = archivio.leggi(1, f"{archivio.PREFISSO_ID}{_id}")
    assert m["attachments"][0]["name"] == "EE00105559_2026_2026.pdf"
    assert "bollette" in m["body_text"]
    assert m["ccRecipients"][0]["emailAddress"]["address"] == "luca.ferri@example.org"
    dati, tipo = archivio.leggi_allegato(1, "10", "EE00105559_2026_2026.pdf", "INBOX")
    assert dati == b"%PDF-1.4 bolletta luce" and tipo == "application/pdf"


def test_stesso_uid_in_cartelle_diverse(st):
    st.salva(1, _mime(mid="<a@x>", oggetto="in arrivo"), folder="INBOX", provider_id="7")
    st.salva(1, _mime(mid="<b@x>", oggetto="inviata"), folder="INBOX.Sent", provider_id="7")
    assert archivio.leggi(1, "7", "INBOX")["subject"] == "in arrivo"
    assert archivio.leggi(1, "7", "INBOX.Sent")["subject"] == "inviata"


def test_il_router_legge_dallarchivio_quando_il_server_non_ce_lha(st, monkeypatch):
    from ade_mail_agent.core import mail_router

    st.salva(1, _mime(), folder="INBOX", provider_id="10")
    monkeypatch.setattr(mail_router, "_account", lambda aid=None: {"id": 1, "type": "imap"})

    def sparita(*a, **k):
        raise ValueError("UID 10 non trovato")
    monkeypatch.setattr(mail_router, "_get_message_provider", sparita)
    monkeypatch.setattr(mail_router, "_get_attachment_provider", sparita)
    assert mail_router.get_message(1, "10", "INBOX")["source"] == "archive"
    dati, _t = mail_router.get_attachment(1, "10", "EE00105559_2026_2026.pdf", "INBOX")
    assert dati.startswith(b"%PDF")


def test_se_non_ce_neanche_nellarchivio_lerrore_resta(st, monkeypatch):
    from ade_mail_agent.core import mail_router

    monkeypatch.setattr(mail_router, "_account", lambda aid=None: {"id": 1, "type": "imap"})

    def sparita(*a, **k):
        raise ValueError("UID 99 non trovato")
    monkeypatch.setattr(mail_router, "_get_message_provider", sparita)
    with pytest.raises(ValueError, match="99"):
        mail_router.get_message(1, "99", "INBOX")


def test_search_mail_restituisce_prima_larchivio(st, monkeypatch):
    from ade_mail_agent import server as srv
    from ade_mail_agent.core import mail_router

    st.salva(1, _mime())
    monkeypatch.setattr(srv.core_accounts, "get_active_account", lambda: {"id": 1})
    monkeypatch.setattr(mail_router, "search_messages", lambda **kw: [])
    r = srv.search_mail(query="mediocasa")
    assert list(r)[0] == "archive"
    assert r["archive"][0]["subject"].startswith("Utenze")


def test_server_irraggiungibile_non_rompe_la_ricerca(st, monkeypatch):
    from ade_mail_agent import server as srv
    from ade_mail_agent.core import mail_router

    st.salva(1, _mime())
    monkeypatch.setattr(srv.core_accounts, "get_active_account", lambda: {"id": 1})

    def giu(**kw):
        raise OSError("getaddrinfo failed")
    monkeypatch.setattr(mail_router, "search_messages", giu)
    r = srv.search_mail(query="bollette")
    assert r["archive"] and r["provider"] == []


# ── sincronizzazione IMAP ───────────────────────────────────────────

class FintoImap:
    """Un server con cartelle, UID e UIDVALIDITY."""

    def __init__(self, cartelle):
        self.cartelle = cartelle            # nome -> {uid: raw}
        self.validita = {n: "1" for n in cartelle}
        self.corrente = None
        self.fetch_fatti = []

    def select(self, nome, readonly=False):
        self.corrente = nome.strip('"')
        return "OK", [str(len(self.cartelle[self.corrente])).encode()]

    def response(self, chiave):
        return "OK", [self.validita[self.corrente].encode()]

    def uid(self, comando, *args):
        uids = sorted(self.cartelle[self.corrente])
        if comando == "search":
            da = int(args[-1].split(":")[0])
            trovati = [u for u in uids if u >= da] or (uids[-1:] if uids else [])
            return "OK", [" ".join(str(u) for u in trovati).encode()]
        if comando == "fetch":
            richiesti = [int(x) for x in args[0].split(",")]
            self.fetch_fatti.extend(richiesti)
            dati = []
            for u in richiesti:
                meta = f'{u} (UID {u} INTERNALDATE "28-Jan-2026 15:13:00 +0100" RFC822 {{1}}'
                dati.append((meta.encode(), self.cartelle[self.corrente][u]))
                dati.append(b")")
            return "OK", dati
        raise AssertionError(comando)


@pytest.fixture()
def imap(monkeypatch):
    from ade_mail_agent.core import imap_client as ic

    server = FintoImap({
        "INBOX": {1: _mime(mid="<1@x>"), 2: _mime(mid="<2@x>", oggetto="seconda")},
        "INBOX.Sent": {5: _mime(mid="<5@x>", oggetto="inviata")},
        "INBOX.Drafts": {9: _mime(mid="<9@x>", oggetto="bozza")},
    })
    monkeypatch.setattr(ic, "_list_folders", lambda conn: list(conn.cartelle))
    return server


def test_sync_imap_salva_tutto_tranne_le_bozze(st, imap):
    esito = archivio_sync.sincronizza_imap(1, imap)
    assert esito["nuovi"] == 3
    assert not st.cerca(1, "bozza")
    assert st.stato(1, "INBOX")["cursor"] == "2"


def test_sync_imap_al_giro_dopo_scarica_solo_le_nuove(st, imap):
    archivio_sync.sincronizza_imap(1, imap)
    imap.fetch_fatti.clear()
    imap.cartelle["INBOX"][3] = _mime(mid="<3@x>", oggetto="terza")
    esito = archivio_sync.sincronizza_imap(1, imap)
    assert esito["nuovi"] == 1 and imap.fetch_fatti == [3]


def test_sync_imap_rispetta_il_tetto_e_riprende(st, imap):
    esito = archivio_sync.sincronizza_imap(1, imap, limite=1)
    assert esito["nuovi"] == 1 and esito["restano"] >= 1
    esito = archivio_sync.sincronizza_imap(1, imap, limite=10)
    assert sum(st.conta(1).values()) == 3


def test_uidvalidity_cambiata_riparte_senza_duplicare(st, imap):
    archivio_sync.sincronizza_imap(1, imap)
    imap.validita["INBOX"] = "2"
    archivio_sync.sincronizza_imap(1, imap)
    assert sum(st.conta(1).values()) == 3


# ── sincronizzazione Graph ──────────────────────────────────────────

def test_sync_graph_primo_caricamento_e_incrementale(st, monkeypatch):
    base = "https://graph.microsoft.com/v1.0"
    messaggi = {f"m{i}": _mime(mid=f"<g{i}@x>", oggetto=f"graph {i}") for i in range(3)}

    def get(url):
        if "/mailFolders?" in url:
            return {"value": [{"id": "inbox", "displayName": "Posta in arrivo"},
                              {"id": "drafts", "displayName": "Bozze"}]}
        if "skiptoken" in url:
            return {"value": [{"id": "m2"}]}
        return {"value": [{"id": "m0"}, {"id": "m1"}],
                "@odata.nextLink": f"{base}/me/mailFolders/inbox/messages?skiptoken=2"}

    scaricati = []

    def get_raw(url):
        mid = url.split("/messages/")[1].split("/")[0]
        scaricati.append(mid)
        return messaggi[mid]

    esito = archivio_sync.sincronizza_graph(5, get=get, get_raw=get_raw)
    assert esito["nuovi"] == 3 and st.stato(5, "inbox")["complete"] == 1
    scaricati.clear()
    esito = archivio_sync.sincronizza_graph(5, get=get, get_raw=get_raw)
    assert esito["nuovi"] == 0 and scaricati == []


# ── import da Outlook ───────────────────────────────────────────────

class FintoAllegato:
    Type, FileName = 1, "EE00105559_2026_2026.pdf"

    def SaveAsFile(self, percorso):
        with open(percorso, "wb") as fh:
            fh.write(b"%PDF-1.4 bolletta luce")


class FintiAllegati:
    Count = 1

    def Item(self, i):
        return FintoAllegato()


class FintoAccessor:
    def __init__(self, props):
        self.props = props

    def GetProperty(self, nome):
        if nome not in self.props:
            raise KeyError(nome)
        return self.props[nome]


class FintoItem:
    Class = 43
    Subject = "Utenze e Iban Mediocasa"
    Body = "Allego le bollette."
    HTMLBody = "<p>Allego le bollette.</p>"
    SenderName, SenderEmailAddress = "Mediocasa", "info@mediocasaimmobiliare.eu"
    Recipients = []
    Attachments = FintiAllegati()

    def __init__(self, intestazioni=""):
        self.PropertyAccessor = FintoAccessor({
            outlook_import._PR_TRANSPORT_HEADERS: intestazioni,
            outlook_import._PR_INTERNET_MESSAGE_ID: "<orig@mediocasa>",
        })

    class ReceivedTime:
        @staticmethod
        def timestamp():
            return 1769609580.0


def test_da_outlook_a_mime_con_le_intestazioni_originali(st, tmp_path):
    intest = ("Message-ID: <orig@mediocasa>\r\nFrom: Mediocasa <info@mediocasaimmobiliare.eu>\r\n"
              "To: conti@fingroupspa.com\r\nCc: luca.ferri@example.org\r\n"
              "Date: Wed, 28 Jan 2026 15:13:00 +0100\r\nSubject: Utenze e Iban Mediocasa\r\n"
              "Received: from mx.example ([1.2.3.4])\r\n\r\n")
    raw, ts = outlook_import.eml_da_item(FintoItem(intest), str(tmp_path))
    campi = archivio.analizza(raw)
    assert campi["message_key"] == "orig@mediocasa"
    assert "luca.ferri@example.org" in campi["cc_addrs"]
    assert "EE00105559_2026_2026.pdf" in campi["attachment_names"]
    assert b"Received:" not in raw.split(b"\n\n")[0]


def test_da_outlook_senza_intestazioni_usa_le_proprieta(st, tmp_path):
    raw, ts = outlook_import.eml_da_item(FintoItem(""), str(tmp_path))
    campi = archivio.analizza(raw)
    assert campi["message_key"] == "orig@mediocasa"
    assert campi["from_addr"] == "info@mediocasaimmobiliare.eu"
    assert ts == 1769609580.0


def test_stessa_mail_da_outlook_e_dal_server_e_una_sola(st, tmp_path):
    raw, ts = outlook_import.eml_da_item(FintoItem(""), str(tmp_path))
    st.salva(1, raw, source="outlook", ripiego_data=ts)
    st.salva(1, _mime(mid="<orig@mediocasa>"), source="imap")
    assert sum(st.conta(1).values()) == 1


# ── l'import parte da solo, una volta ───────────────────────────────

@pytest.fixture()
def lanci(monkeypatch):
    monkeypatch.setattr(outlook_import, "disponibile", lambda: True)
    fatti = []
    return fatti, (lambda cmd: fatti.append(cmd) or 4321)


def test_primo_giro_lancia_limport(st, lanci):
    fatti, lancia = lanci
    assert outlook_import.avvia_se_serve(1, st=st, lancia=lancia) == "avviato"
    assert fatti and fatti[0][-2:] == ["--account-id", "1"]
    assert st.import_stato(1, "outlook")["status"] == "running"


def test_in_corso_non_si_rilancia(st, lanci):
    fatti, lancia = lanci
    outlook_import.avvia_se_serve(1, st=st, lancia=lancia)
    assert outlook_import.avvia_se_serve(
        1, st=st, lancia=lancia, pid_vivo=lambda pid: True) == "in-corso"
    assert len(fatti) == 1


def test_fatto_non_si_rifa(st, lanci):
    fatti, lancia = lanci
    st.import_segna(1, "outlook", "done", count=6000)
    assert outlook_import.avvia_se_serve(1, st=st, lancia=lancia) == "fatto"
    assert fatti == []


def test_dopo_tre_fallimenti_si_smette(st, lanci):
    fatti, lancia = lanci
    for _ in range(3):
        outlook_import.avvia_se_serve(1, st=st, lancia=lancia, pid_vivo=lambda p: False)
    assert outlook_import.avvia_se_serve(
        1, st=st, lancia=lancia, pid_vivo=lambda p: False) == "abbandonato"
    assert len(fatti) == 3


def test_senza_outlook_non_si_fa_niente(st, monkeypatch):
    monkeypatch.setattr(outlook_import, "disponibile", lambda: False)
    assert outlook_import.avvia_se_serve(1, st=st, lancia=lambda c: 1) == "non-disponibile"


# ── la ricerca IMAP con gli accenti ─────────────────────────────────

class ConnRegistra:
    def __init__(self):
        self.chiamate, self.literal = [], None

    def uid(self, *args):
        self.chiamate.append((args, self.literal))
        return "OK", [b"4 5"]


def test_ricerca_imap_con_accenti_usa_charset_e_literal():
    from ade_mail_agent.core import imap_client as ic

    conn = ConnRegistra()
    assert ic._uid_search_safe(conn, "TEXT", "proprietà") == [b"4", b"5"]
    args, literal = conn.chiamate[0]
    assert args[:4] == ("search", "CHARSET", "UTF-8", "TEXT")
    assert literal == "proprietà".encode("utf-8")


def test_ricerca_imap_ascii_senza_charset():
    from ade_mail_agent.core import imap_client as ic

    conn = ConnRegistra()
    ic._uid_search_safe(conn, "FROM", "mediocasa")
    args, _ = conn.chiamate[0]
    assert args == ("search", None, "FROM", '"mediocasa"')


def test_formato_data_da_outlook_valido():
    assert email.utils.parsedate_to_datetime(email.utils.formatdate(1769609580.0))


# ── mail rotte: si archiviano e non fermano le altre ────────────────

def test_message_id_vuoto_non_manda_in_errore(st):
    """28/09: `Message-ID: <>` faceva andare in IndexError il parser e
    fermava la sincronizzazione dell'intera casella."""
    raw = (b"Message-ID: <>\r\nFrom: Mario <mario@example.com>\r\n"
           b"Subject: bolletta\r\nDate: Wed, 28 Jan 2026 15:13:00 +0100\r\n\r\ntesto")
    _id, nuovo = st.salva(1, raw)
    assert nuovo
    assert st.cerca(1, "bolletta")[0]["from"]["emailAddress"]["address"] == "mario@example.com"
    assert archivio.leggi(1, f"{archivio.PREFISSO_ID}{_id}")["subject"] == "bolletta"


def test_mail_illeggibile_resta_comunque_in_archivio(st):
    campi = archivio.analizza(b"\xff\xfe\x00 non e' una mail")
    assert campi["message_key"].startswith(("sha1:", "h:"))


def test_una_mail_che_non_si_salva_non_ferma_la_cartella(st, imap, monkeypatch):
    originale = st.salva

    def salva(account_id, raw, **kw):
        if kw.get("provider_id") == "1":
            raise RuntimeError("mail rotta")
        return originale(account_id, raw, **kw)
    monkeypatch.setattr(st, "salva", salva)
    esito = archivio_sync.sincronizza_imap(1, imap)
    assert esito["errori"] == 1 and esito["nuovi"] == 2
    assert st.stato(1, "INBOX")["cursor"] == "2"      # il cursore e' andato avanti
