"""Edge case parsing IMAP — incluso il bug reale 'Header' object has no
attribute 'split' (header From/Subject malformati che il parser email
restituisce come email.header.Header invece che str)."""
import email
import email.header

from ade_mail_agent.core import imap_client


def _malformed_msg() -> email.message.Message:
    """Messaggio il cui From contiene byte non-ASCII grezzi (non RFC2047):
    msg.get('From') restituisce un oggetto Header, non una str."""
    raw = (
        b"From: Caff\xe8 Ross\xec <caffe@example.it>\r\n"
        b"To: dest@example.it\r\n"
        b"Subject: Listino \xe8 aggiornato\r\n"
        b"Date: Wed, 13 Aug 2026 10:00:00 +0200\r\n"
        b"\r\n"
        b"corpo\r\n"
    )
    return email.message_from_bytes(raw)


def test_msg_get_restituisce_header_non_str():
    """Precondizione del bug: senza coercizione, .split() esploderebbe."""
    msg = _malformed_msg()
    assert isinstance(msg.get("From"), email.header.Header)


def test_hdr_str_coercizza_header():
    msg = _malformed_msg()
    out = imap_client._hdr_str(msg.get("From"))
    assert isinstance(out, str)
    assert "caffe@example.it" in out
    assert imap_client._hdr_str(None) == ""
    assert imap_client._hdr_str("gia' str") == "gia' str"


def test_decode_header_accetta_header_object():
    msg = _malformed_msg()
    subject = imap_client._decode_header(msg.get("Subject"))
    assert isinstance(subject, str)
    assert "aggiornato" in subject


def test_split_from_su_header_malformato_non_esplode():
    """Il pattern usato nel fetch batch: name/addr da From coercizzato."""
    msg = _malformed_msg()
    from_raw = imap_client._hdr_str(msg.get("From", ""))
    name_part = from_raw.split("<")[0].strip()
    addr_part = from_raw.split("<")[-1].strip(">") if "<" in from_raw else from_raw.strip()
    assert addr_part == "caffe@example.it"
    assert name_part  # il nome resta, anche se con escape


def test_decode_header_rfc2047_normale():
    val = "=?utf-8?B?TGlzdGlubyDDqCBwcm9udG8=?="
    assert imap_client._decode_header(val) == "Listino è pronto"


def test_decode_header_none_e_vuoto():
    assert imap_client._decode_header(None) == ""
    assert imap_client._decode_header("") == ""
