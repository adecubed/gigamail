"""OpenPGP end-to-end encryption (core/pgp.py).

The correspondent is a key outside our store, as on another computer: we
only ever see its public half, learned from the Autocrypt header of its
mail. Our own key lives in the store.
"""
import base64
import email
import sqlite3
from contextlib import closing
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import pytest

pysequoia = pytest.importorskip("pysequoia")

from gigamail.core import imap_client, mail_router, pgp  # noqa: E402
from gigamail.core.data_paths import db_path  # noqa: E402

ME = "mario.rossi@example.com"
PEER = "anna.bianchi@example.com"


@pytest.fixture(autouse=True)
def _empty_store():
    path = db_path(pgp.DB_NAME)
    if path.exists():
        path.unlink()
    yield


@pytest.fixture()
def peer():
    """A correspondent on another machine: its secret key is not ours."""
    return pysequoia.Tsk.generate(user_id=f"<{PEER}>")


def _autocrypt_of(tsk, addr, extra=""):
    b64 = base64.b64encode(bytes(tsk.extract_certificate())).decode()
    return f"addr={addr};{extra} prefer-encrypt=mutual; keydata={b64}"


def _mail_from_peer(peer, date="Thu, 12 Nov 2026 10:00:00 +0100", addr=PEER):
    m = MIMEMultipart()
    m["From"], m["To"], m["Subject"], m["Date"] = PEER, ME, "Hello", date
    m["Autocrypt"] = _autocrypt_of(peer, addr)
    m.attach(MIMEText("first contact", "plain", "utf-8"))
    return email.message_from_bytes(m.as_bytes())


def _clear_mail(subject="Contract draft", body="The confidential terms."):
    m = MIMEMultipart()
    m["From"], m["To"], m["Subject"] = ME, PEER, subject
    m.attach(MIMEText(body, "plain", "utf-8"))
    att = MIMEApplication(b"%PDF-1.4 terms", "pdf")
    att.add_header("Content-Disposition", 'attachment; filename="terms.pdf"')
    m.attach(att)
    return m


class _SMTP:
    sent = []

    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def login(self, *a):
        pass

    def starttls(self, **k):
        pass

    def sendmail(self, sender, recipients, payload):
        _SMTP.sent.append((sender, recipients, payload))
        return {}


@pytest.fixture()
def smtp(monkeypatch):
    _SMTP.sent = []
    monkeypatch.setattr(imap_client.smtplib, "SMTP_SSL", _SMTP)
    monkeypatch.setattr(imap_client.smtplib, "SMTP", _SMTP)
    saved = []
    monkeypatch.setattr(imap_client, "_append_to_sent_folder",
                        lambda h, p, a, pw, raw: saved.append(raw) or True)
    _SMTP.saved = saved
    return _SMTP


def _send(**kw):
    args = dict(smtp_host="smtp.example.com", smtp_port=465, email_addr=ME,
                password="x", to=PEER, subject="Contract draft",
                body="The confidential terms.", imap_host="imap.example.com",
                imap_port=993, imap_password="x")
    args.update(kw)
    return imap_client.send_message(**args)


# ── keys ────────────────────────────────────────────────────────────

def test_autocrypt_header_from_a_peer_is_learned(peer):
    assert pgp.learn_autocrypt(_mail_from_peer(peer)) == PEER
    assert pgp.peer_cert(PEER).fingerprint == peer.extract_certificate().fingerprint


def test_autocrypt_header_for_another_address_is_ignored(peer):
    # Anyone can write a header: it only counts for the address that sent it.
    msg = _mail_from_peer(peer, addr="someone.else@example.com")
    assert pgp.learn_autocrypt(msg) is None
    assert pgp.peer_cert("someone.else@example.com") is None
    assert pgp.peer_cert(PEER) is None


def test_an_older_mail_does_not_replace_a_newer_key(peer):
    pgp.learn_autocrypt(_mail_from_peer(peer, date="Thu, 12 Nov 2026 10:00:00 +0100"))
    old = pysequoia.Tsk.generate(user_id=f"<{PEER}>")
    pgp.learn_autocrypt(_mail_from_peer(old, date="Mon, 02 Nov 2026 10:00:00 +0100"))
    assert pgp.peer_cert(PEER).fingerprint == peer.extract_certificate().fingerprint


def test_own_secret_key_is_not_stored_in_clear():
    tsk = pgp.own_key(ME)
    raw = db_path(pgp.DB_NAME).read_bytes()
    assert bytes(tsk) not in raw
    with closing(sqlite3.connect(str(db_path(pgp.DB_NAME)))) as conn:
        (stored,) = conn.execute("SELECT secret_enc FROM own_keys").fetchone()
    assert base64.b64encode(bytes(tsk)).decode() not in stored
    # The same key comes back.
    assert pgp.own_key(ME).extract_certificate().fingerprint == \
        tsk.extract_certificate().fingerprint



def test_the_key_store_file_is_closed_after_every_use(monkeypatch, peer):
    """On Windows an open SQLite file cannot be deleted or replaced."""
    opened = []
    real_connect = sqlite3.connect

    def tracking_connect(*args, **kwargs):
        conn = real_connect(*args, **kwargs)
        opened.append(conn)
        return conn

    monkeypatch.setattr(pgp.sqlite3, "connect", tracking_connect)
    pgp.own_key(ME)
    pgp.open_message(email.message_from_bytes(_encrypted_with_id(peer)))
    assert opened
    for conn in opened:
        with pytest.raises(sqlite3.ProgrammingError):
            conn.execute("SELECT 1")


def test_autocrypt_header_fits_mail_line_limits():
    m = MIMEMultipart()
    m["From"] = ME
    m["Autocrypt"] = pgp.autocrypt_header(ME)
    assert max(len(line) for line in m.as_bytes().split(b"\n")) < 998


# ── encrypt ─────────────────────────────────────────────────────────

def test_encrypted_mail_hides_body_subject_and_attachment(peer):
    pgp.learn_autocrypt(_mail_from_peer(peer))
    out = pgp.encrypt_message(_clear_mail(), ME, [PEER]).as_bytes()
    assert b"multipart/encrypted" in out
    assert b"confidential" not in out
    assert b"Contract draft" not in out
    assert b"terms.pdf" not in out
    assert b"Subject: ..." in out


def test_only_the_recipient_opens_it_and_sees_who_signed(peer):
    pgp.learn_autocrypt(_mail_from_peer(peer))
    out = pgp.encrypt_message(_clear_mail(), ME, [PEER]).as_bytes()
    data = email.message_from_bytes(out).get_payload()[1].get_payload(decode=True)

    stranger = pysequoia.Tsk.generate(user_id="<stranger@example.com>")
    with pytest.raises(RuntimeError):
        pysequoia.decrypt(bytes=data, decryptor=stranger.decryptor())

    me_cert = pgp.own_key(ME).extract_certificate()
    clear = pysequoia.decrypt(bytes=data, decryptor=peer.decryptor(),
                              store=lambda ids: [me_cert])
    inner = email.message_from_bytes(clear.bytes)
    assert inner["Subject"] == "Contract draft"
    assert clear.valid_sigs
    assert str(clear.valid_sigs[0].certificate).lower() == me_cert.fingerprint.lower()


def test_no_key_for_a_recipient_means_no_encryption():
    with pytest.raises(pgp.PgpError) as e:
        pgp.encrypt_message(_clear_mail(), ME, [PEER])
    assert PEER in str(e.value)


def test_status_names_the_recipients_without_key(peer):
    pgp.learn_autocrypt(_mail_from_peer(peer))
    st = pgp.status(ME, [PEER, "luca.verdi@example.com"])
    assert st["can_encrypt"] is False
    assert st["missing"] == ["luca.verdi@example.com"]
    assert pgp.status(ME, [PEER])["can_encrypt"] is True


# ── decrypt ─────────────────────────────────────────────────────────

def _encrypted_from_peer(peer, subject="Offer", body="Our best price."):
    """A mail the correspondent encrypted for us, as it arrives."""
    inner = MIMEMultipart("mixed")
    inner.set_param("protected-headers", "v1")
    inner["Subject"] = subject
    inner.attach(MIMEText(body, "plain", "utf-8"))
    me_cert = pgp.own_key(ME).extract_certificate()
    ct = pysequoia.encrypt(bytes=inner.as_bytes(), recipients=[me_cert],
                           signer=peer.signer())
    outer = MIMEMultipart("encrypted", protocol="application/pgp-encrypted")
    outer["From"], outer["To"], outer["Subject"] = PEER, ME, "..."
    outer["Date"] = "Thu, 12 Nov 2026 11:00:00 +0100"
    outer["Autocrypt"] = _autocrypt_of(peer, PEER)
    outer.attach(MIMEApplication(b"Version: 1\n", "pgp-encrypted"))
    outer.attach(MIMEApplication(ct, "octet-stream"))
    return outer.as_bytes()


def test_incoming_encrypted_mail_is_opened_and_signature_checked(peer):
    raw = _encrypted_from_peer(peer)
    inner, info = pgp.open_message(email.message_from_bytes(raw), ME)
    assert info["decrypted"] is True
    assert info["signature_valid"] is True
    assert info["signer"] == PEER and info["signer_matches_from"] is True
    assert inner["Subject"] == "Offer"
    assert inner["From"] == PEER
    assert inner.get_payload()[0].get_payload(decode=True) == b"Our best price."


def test_mail_for_someone_else_stays_closed(peer):
    stranger = pysequoia.Tsk.generate(user_id="<stranger@example.com>")
    pgp.own_key(ME)
    ct = pysequoia.encrypt(bytes=b"Subject: x\n\nsecret",
                           recipients=[stranger.extract_certificate()])
    outer = MIMEMultipart("encrypted", protocol="application/pgp-encrypted")
    outer["From"], outer["To"] = PEER, ME
    outer.attach(MIMEApplication(b"Version: 1\n", "pgp-encrypted"))
    outer.attach(MIMEApplication(ct, "octet-stream"))
    msg = email.message_from_bytes(outer.as_bytes())
    same, info = pgp.open_message(msg, ME)
    assert same is msg
    assert info["encrypted"] is True and info["decrypted"] is False
    assert info["error"]


def test_a_secret_key_in_a_header_is_stored_public_only(peer):
    msg = _mail_from_peer(peer)
    msg.replace_header("Autocrypt", "addr=%s; keydata=%s" % (
        PEER, base64.b64encode(bytes(peer)).decode()))
    assert pgp.learn_autocrypt(msg) == PEER
    with closing(sqlite3.connect(str(db_path(pgp.DB_NAME)))) as conn:
        (stored,) = conn.execute("SELECT keydata FROM peer_keys").fetchone()
    assert stored == bytes(peer.extract_certificate())


def test_clear_mail_has_no_encryption_info(peer):
    msg = _mail_from_peer(peer)
    same, info = pgp.open_message(msg, ME)
    assert same is msg and info is None


# ── send path ───────────────────────────────────────────────────────

def test_every_smtp_mail_carries_our_autocrypt_header(smtp):
    out = _send()
    assert out["success"] is True
    payload = smtp.sent[0][2]
    assert "Autocrypt: addr=" + ME in payload
    assert "multipart/mixed" in payload
    assert base64.b64encode(b"The confidential terms.").decode() in payload


def test_encrypted_send_leaves_and_is_saved_encrypted(smtp, peer):
    pgp.learn_autocrypt(_mail_from_peer(peer))
    out = _send(encrypt=True)
    assert out["success"] is True
    payload = smtp.sent[0][2]
    assert "multipart/encrypted" in payload
    assert "confidential" not in payload and "Contract draft" not in payload
    assert base64.b64encode(b"The confidential terms.").decode() not in payload
    assert b"confidential" not in smtp.saved[0]
    # The copy in Sent opens with our own key.
    inner, info = pgp.open_message(email.message_from_bytes(smtp.saved[0]), ME)
    assert info["decrypted"] is True
    assert "Contract draft" in str(inner["Subject"])


def test_encrypt_without_a_key_sends_nothing(smtp):
    out = _send(encrypt=True)
    assert out["success"] is False
    assert smtp.sent == [] and smtp.saved == []
    assert PEER in out["error"]


def test_encrypt_with_bcc_sends_nothing(smtp, peer):
    pgp.learn_autocrypt(_mail_from_peer(peer))
    out = _send(encrypt=True, bcc=["luca.verdi@example.com"])
    assert out["success"] is False and smtp.sent == []


@pytest.mark.parametrize("account", [
    {"id": 1, "type": "microsoft", "email": ME},
    {"id": 1, "type": "imap", "email": ME, "demo": True},
])
def test_encrypt_is_refused_where_we_do_not_build_the_mime(monkeypatch, account):
    monkeypatch.setattr(mail_router, "_account", lambda account_id=None: account)
    monkeypatch.setattr(mail_router, "_demo", lambda a: bool(a.get("demo")))
    called = []
    monkeypatch.setattr(mail_router.ms_mail, "send_message",
                        lambda *a, **k: called.append(1) or {"success": True})
    monkeypatch.setattr(mail_router.demo, "send_message",
                        lambda *a, **k: called.append(1) or {"success": True})
    out = mail_router._send_backend(account_id=1, to=PEER, subject="s",
                                    body="b", encrypt=True)
    assert out["success"] is False and called == []
    assert mail_router.encryption_status(1, [PEER])["can_encrypt"] is False


def test_router_passes_encrypt_down_to_smtp(monkeypatch):
    monkeypatch.setattr(mail_router, "_account", lambda account_id=None: {
        "id": 1, "type": "imap", "email": ME, "data": {}})
    seen = {}
    monkeypatch.setattr(imap_client, "send_message",
                        lambda *a, **k: seen.update(k) or {"success": True})
    mail_router._send_backend(account_id=1, to=PEER, subject="s", body="b",
                              encrypt=True)
    assert seen["encrypt"] is True


# ── archive ─────────────────────────────────────────────────────────

def test_archived_encrypted_mail_is_opened_when_read(peer):
    from gigamail.core import archivio
    raw = _encrypted_from_peer(peer, subject="Archived offer")
    row = {"id": 7, "subject": "...", "from_addr": PEER, "from_name": "",
           "date_utc": "", "folder": "INBOX"}
    msg = archivio.messaggio(row, raw)
    assert msg["subject"] == "Archived offer"
    assert "Our best price." in msg["body_text"]
    assert msg["encryption"]["signer_matches_from"] is True


# ── an opened mail is kept decrypted ────────────────────────────────

@pytest.fixture()
def archive(tmp_path):
    from gigamail.core import archivio
    archivio.set_store(archivio.ArchiveStore(tmp_path / "arch.db", tmp_path / "mail"))
    yield archivio
    archivio.set_store(None)


def _encrypted_with_id(peer, **kw):
    msg = email.message_from_bytes(_encrypted_from_peer(peer, **kw))
    msg["Message-ID"] = "<offer-1@example.com>"
    return msg.as_bytes()


def _lose_the_key():
    db_path(pgp.DB_NAME).unlink()


def test_opened_mail_stays_readable_after_the_key_is_lost(archive, peer):
    rowid, _ = archive.store().salva(1, _encrypted_with_id(peer), folder="INBOX",
                                     provider_id="5")
    first = archive.leggi(1, f"arch-{rowid}", keep_opened=True)
    assert "Our best price." in first["body_text"]
    _lose_the_key()
    again = archive.leggi(1, f"arch-{rowid}")
    assert again["subject"] == "Offer"
    assert "Our best price." in again["body_text"]
    assert again["encryption"]["signer"] == PEER
    assert again["encryption"]["signer_matches_from"] is True
    # The archive index holds the text now: search finds it.
    assert [m["id"] for m in archive.cerca(1, "price")] == [f"arch-{rowid}"]


def test_a_preview_does_not_keep_the_mail_decrypted(archive, peer):
    rowid, _ = archive.store().salva(1, _encrypted_with_id(peer), folder="INBOX")
    archive.leggi(1, f"arch-{rowid}")              # e.g. a search preview
    _lose_the_key()
    closed = archive.leggi(1, f"arch-{rowid}")
    assert "Our best price." not in closed["body_text"]
    assert closed["encryption"]["decrypted"] is False


def test_the_encrypted_copy_from_the_server_does_not_replace_the_kept_one(archive, peer):
    raw = _encrypted_with_id(peer)
    rowid, _ = archive.store().salva(1, raw, source="outlook")
    archive.leggi(1, f"arch-{rowid}", keep_opened=True)
    _lose_the_key()
    # The sync later sees the same mail on the server, a "better" source.
    archive.store().salva(1, raw, folder="INBOX", provider_id="5", source="imap")
    kept = archive.leggi(1, f"arch-{rowid}")
    assert "Our best price." in kept["body_text"]
    assert archive.store().riga(1, "5")["folder"] == "INBOX"


def test_a_clear_mail_is_not_marked_as_opened(archive):
    rowid, _ = archive.store().salva(1, _clear_mail().as_bytes(), folder="INBOX")
    msg = archive.leggi(1, f"arch-{rowid}", keep_opened=True)
    assert msg["encryption"] is None
    assert archive.store().riga(1, f"arch-{rowid}")["opened_encryption"] == ""


def test_an_executable_hidden_by_the_encryption_is_not_kept(archive, peer):
    inner = MIMEMultipart("mixed")
    inner["Subject"] = "Invoice"
    inner.attach(MIMEText("See attached.", "plain", "utf-8"))
    exe = MIMEApplication(b"MZ\x90\x00 program", "octet-stream")
    exe.add_header("Content-Disposition", 'attachment; filename="invoice.exe"')
    inner.attach(exe)
    ct = pysequoia.encrypt(bytes=inner.as_bytes(),
                           recipients=[pgp.own_key(ME).extract_certificate()],
                           signer=peer.signer())
    outer = MIMEMultipart("encrypted", protocol="application/pgp-encrypted")
    outer["From"], outer["To"], outer["Subject"] = PEER, ME, "..."
    outer["Message-ID"] = "<invoice-1@example.com>"
    outer.attach(MIMEApplication(b"Version: 1\n", "pgp-encrypted"))
    outer.attach(MIMEApplication(ct, "octet-stream"))
    rowid, _ = archive.store().salva(1, outer.as_bytes(), folder="INBOX")
    archive.leggi(1, f"arch-{rowid}", keep_opened=True)
    raw = archive.store().raw(archive.store().riga(1, f"arch-{rowid}"))
    assert b"MZ\x90\x00 program" not in raw
    with pytest.raises(archive.AttachmentRemoved):
        archive.leggi_allegato(1, f"arch-{rowid}", "invoice.exe")


def test_reading_from_the_server_keeps_it_decrypted(monkeypatch, archive, peer):
    raw = _encrypted_with_id(peer)
    monkeypatch.setattr(mail_router, "_account",
                        lambda _id=None: {"id": 1, "type": "imap", "email": ME})
    monkeypatch.setattr(mail_router, "_imap_credentials",
                        lambda a: ("imap.example.com", 993, ME, "secret"))

    def fake_get_message(*a, on_opened=None, **k):
        opened, info = pgp.open_raw(raw, ME)
        on_opened(raw, opened, info)
        return {"id": "5", "encryption": info}

    monkeypatch.setattr(imap_client, "get_message", fake_get_message)
    mail_router.get_message(1, "5", "INBOX")
    _lose_the_key()
    kept = archive.leggi(1, "5", "INBOX")
    assert "Our best price." in kept["body_text"]
    assert kept["encryption"]["signer"] == PEER


@pytest.mark.parametrize("signed_by_stranger", [True, False])
def test_a_mail_without_a_known_signature_still_opens(signed_by_stranger):
    """A platform that encrypts for us but sends no Autocrypt header: we
    cannot check its signature, the mail is still ours to read."""
    stranger = pysequoia.Tsk.generate(user_id="<votes@example.com>")
    inner = MIMEMultipart("mixed")
    inner["Subject"] = "Ballot"
    inner.attach(MIMEText("Ballot 12: option B.", "plain", "utf-8"))
    ct = pysequoia.encrypt(bytes=inner.as_bytes(),
                           recipients=[pgp.own_key(ME).extract_certificate()],
                           signer=stranger.signer() if signed_by_stranger else None)
    outer = MIMEMultipart("encrypted", protocol="application/pgp-encrypted")
    outer["From"], outer["To"], outer["Subject"] = "votes@example.com", ME, "..."
    outer.attach(MIMEApplication(b"Version: 1\n", "pgp-encrypted"))
    outer.attach(MIMEApplication(ct, "octet-stream"))
    opened, info = pgp.open_message(email.message_from_bytes(outer.as_bytes()), ME)
    assert info["decrypted"] is True
    assert info["signature_valid"] is False and info["signer"] is None
    assert "option B" in opened.get_payload()[0].get_payload(decode=True).decode()
