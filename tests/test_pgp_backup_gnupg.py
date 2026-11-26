"""The key backup file against the real GnuPG program.

The backup is a standard protected OpenPGP key: GnuPG must import it, ask
for the passphrase and sign or decrypt with it. And a key GnuPG made and
protected must restore into GigaMail. Without `gpg` these tests skip; with
GIGAMAIL_REQUIRE_GNUPG=1 (CI on Linux) a missing `gpg` fails them instead.
"""
import email
import os
import re
import shutil
import subprocess
import tempfile
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import pytest

pysequoia = pytest.importorskip("pysequoia")

from gigamail.core import pgp, pgp_backup  # noqa: E402
from gigamail.core.data_paths import db_path  # noqa: E402

ME = "mario.rossi@example.com"
PEER = "anna.bianchi@example.com"
PASSPHRASE = "correct horse 42"


@pytest.fixture(autouse=True)
def _empty_store():
    path = db_path(pgp.DB_NAME)
    if path.exists():
        path.unlink()
    yield


def _fpr(key):
    return key.extract_certificate().fingerprint


def _clear_mail():
    m = MIMEMultipart()
    m["From"], m["To"], m["Subject"] = ME, PEER, "Contract draft"
    m.attach(MIMEText("The confidential terms.", "plain", "utf-8"))
    return m


TIMEOUT = 60

# GnuPG on libgcrypt 1.12.0 (the Ubuntu 26.04 runners) signs with an imported
# key but fails to decrypt with its Curve25519 subkey, answering "Bad
# passphrase" to the right one. Seen in CI on our backup, where the same
# tests pass on libgcrypt 1.11; other projects report the same on keys GnuPG
# made itself, as a libgcrypt bug (GnuPG T8094) fixed in 1.12.1. Only that
# version, and only that answer, is set aside.
BROKEN_LIBGCRYPT = "1.12.0"

# GnuPG 2.4 encrypts to a key that advertises OCB with the AEAD packet of
# the draft, which the library refuses to read. Keys made for these tests
# advertise no AEAD, so a mail to them is a plain MDC-protected message,
# what most GnuPG users still send and receive.
NO_AEAD = "AES256 AES192 AES SHA512 SHA384 SHA256 ZLIB ZIP Uncompressed"


def _find_gpg():
    """The `gpg` executable, or None. Git for Windows ships one that is not
    always on the Windows PATH: look next to git."""
    found = shutil.which("gpg")
    if found:
        return found
    git = shutil.which("git")
    if git:
        root = Path(git).resolve().parent.parent
        for base in (root, root.parent):
            for rel in ("usr/bin/gpg.exe", "usr/bin/gpg"):
                cand = base / rel
                if cand.is_file():
                    return str(cand)
    return None


def _home_spelling(exe, home):
    """How to write the home folder for this `gpg`. Git for Windows' gpg is
    an MSYS program: it wants /c/Users/... (it does not find its agent with
    C:\\ paths). Any other gpg takes the native spelling."""
    if os.name == "nt":
        p = Path(exe).resolve()
        if p.parent.name == "bin" and p.parent.parent.name == "usr":
            drive, rest = os.path.splitdrive(home)
            return "/" + drive[0].lower() + rest.replace("\\", "/")
    return home


def _unavailable(reason):
    if os.environ.get("GIGAMAIL_REQUIRE_GNUPG") == "1":
        pytest.fail(reason)
    pytest.skip(reason)


class Gnupg:
    def __init__(self, exe, home):
        self.exe = exe
        self.home = home
        # English messages whatever the machine's language: one test reads
        # what gpg says on stderr.
        self.env = dict(os.environ, GNUPGHOME=_home_spelling(exe, home),
                        LANGUAGE="en", LC_ALL="C")
        # Never a window, never a wait for a person: the agent accepts
        # passphrases from stdin only, and its pinentry fails at once.
        failing = "/usr/bin/false" if os.name == "nt" else "/bin/false"
        (Path(home) / "gpg-agent.conf").write_text(
            "allow-loopback-pinentry\npinentry-program " + failing + "\n",
            encoding="ascii")
        self.data_dir = tempfile.mkdtemp(prefix="gmd")
        out = self.gpg("--version").stdout.decode("utf-8", "replace")
        m = re.search(r"gpg \(GnuPG[^)]*\) (\d+)\.(\d+)", out)
        self.version = (int(m.group(1)), int(m.group(2))) if m else (0, 0)
        m = re.search(r"libgcrypt (\d+\.\d+\.\d+)", out)
        self.libgcrypt = m.group(1) if m else ""

    def run(self, program, *args, input=None):
        return subprocess.run([program, *args], input=input, env=self.env,
                              capture_output=True, timeout=TIMEOUT)

    def gpg(self, *args, input=None):
        return self.run(self.exe, "--batch", "--no-tty",
                       "--pinentry-mode", "loopback", *args, input=input)

    def _with_passphrase(self, passphrase, *args, data=None):
        """Passphrase on stdin (--passphrase-fd 0); the data, if any, goes
        in a file because stdin is taken."""
        argv = ["--passphrase-fd", "0", *args]
        if data is not None:
            path = Path(self.data_dir) / "data.bin"
            path.write_bytes(data)
            argv.append(str(path))
        return self.gpg(*argv, input=passphrase.encode("utf-8") + b"\n")

    def decrypt(self, cipher, passphrase):
        return self._with_passphrase(passphrase, "--decrypt", data=cipher)

    def plaintext(self, cipher, passphrase):
        """What gpg decrypts; when it does not, the failure carries what gpg
        said, so a red CI names the reason."""
        done = self.decrypt(cipher, passphrase)
        said = done.stderr.decode("utf-8", "replace")
        if (done.returncode != 0 and self.libgcrypt == BROKEN_LIBGCRYPT
                and ("Bad passphrase" in said or "Bad secret key" in said)):
            # Not a missing GnuPG, so a skip even where GnuPG is required:
            # the other systems in CI measure this step.
            pytest.skip("libgcrypt " + BROKEN_LIBGCRYPT + " cannot reliably use "
                        "an imported Curve25519 secret key (GnuPG T8094): "
                        "decryption by GnuPG is not measured on this system")
        assert done.returncode == 0, (
            self.gpg("--version").stdout.decode("utf-8", "replace")[:80]
            + "\n" + done.stderr.decode("utf-8", "replace"))
        return done.stdout

    def clearsign(self, data, user, passphrase):
        return self._with_passphrase(passphrase, "--local-user", user,
                                     "--clearsign", "--output", "-", data=data)

    def generate(self, user, algo, passphrase):
        """A key with a certify+sign primary of `algo` and an encryption
        subkey (GnuPG makes none with usage "default" for these)."""
        made = self._with_passphrase(
            passphrase, "--default-preference-list", NO_AEAD,
            "--quick-generate-key", user, algo, "cert,sign", "never")
        if made.returncode != 0:
            return made
        listing = self.gpg("--list-keys", "--with-colons", user).stdout.decode()
        fpr = re.search(r"^fpr:+([0-9A-F]+):", listing, re.M).group(1)
        subkey = "cv25519" if algo == "ed25519" else algo
        return self._with_passphrase(
            passphrase, "--quick-add-key", fpr, subkey, "encr", "never")

    def export_secret(self, user, passphrase):
        done = self._with_passphrase(passphrase, "--armor",
                                     "--export-secret-keys", user)
        assert done.returncode == 0, done.stderr
        return done.stdout

    def encrypt_to(self, user, data):
        done = self.gpg("--trust-model", "always", "-r", user, "-a", "-e",
                        input=data)
        assert done.returncode == 0, done.stderr
        return done.stdout

    def forget_passphrases(self):
        """The agent caches a right passphrase and would answer for a wrong
        one."""
        self.run(self.gpgconf(), "--kill", "gpg-agent")

    def gpgconf(self):
        found = shutil.which("gpgconf")
        if found:
            return found
        return str(Path(self.exe).with_name("gpgconf" + Path(self.exe).suffix))

    def close(self):
        try:
            self.run(self.gpgconf(), "--kill", "all")
        except Exception:
            pass
        shutil.rmtree(self.home, ignore_errors=True)
        shutil.rmtree(self.data_dir, ignore_errors=True)


@pytest.fixture()
def gnupg():
    exe = _find_gpg()
    if not exe:
        _unavailable("GnuPG not installed")
    # A short path: the agent's socket path has a length limit, so not
    # pytest's long tmp_path.
    home = tempfile.mkdtemp(prefix="gm")
    try:
        g = Gnupg(exe, home)
    except Exception:
        shutil.rmtree(home, ignore_errors=True)
        _unavailable("GnuPG not usable")
    try:
        probe = g.gpg("--list-keys")
        if probe.returncode != 0:
            _unavailable("GnuPG not usable: " + probe.stderr.decode(
                "utf-8", "replace")[:200])
        yield g
    finally:
        g.close()


def _inner_mime(text):
    return (b"Content-Type: text/plain; charset=utf-8\r\n\r\n"
            + text.encode("utf-8"))


def _pgp_mime(ciphertext):
    """The RFC 3156 envelope around armored ciphertext, as a mail client
    sends it."""
    outer = MIMEMultipart("encrypted", protocol="application/pgp-encrypted")
    outer["From"], outer["To"], outer["Subject"] = (
        PEER, ME, "...")
    outer.attach(MIMEApplication(b"Version: 1\n", "pgp-encrypted"))
    outer.attach(MIMEApplication(ciphertext, "octet-stream"))
    return email.message_from_bytes(outer.as_bytes())


def test_gnupg_imports_the_backup_and_needs_the_passphrase(gnupg, tmp_path):
    key = pgp.own_key(ME)
    backup = tmp_path / "backup.asc"
    pgp_backup.export_backup(backup, PASSPHRASE)
    assert gnupg.gpg("--import", str(backup)).returncode == 0
    listing = gnupg.gpg("--list-secret-keys", "--with-colons").stdout.decode()
    assert _fpr(key).upper() in listing.upper()

    cipher = gnupg.encrypt_to(ME, b"hello")
    assert gnupg.plaintext(cipher, PASSPHRASE) == b"hello"
    gnupg.forget_passphrases()
    assert gnupg.decrypt(cipher, "wrong passphrase").returncode != 0


def test_gnupg_signs_with_the_backup(gnupg, tmp_path):
    pgp.own_key(ME)
    backup = tmp_path / "backup.asc"
    pgp_backup.export_backup(backup, PASSPHRASE)
    assert gnupg.gpg("--import", str(backup)).returncode == 0
    signed = gnupg.clearsign(b"hello", ME, PASSPHRASE)
    assert signed.returncode == 0, signed.stderr
    assert b"BEGIN PGP SIGNED MESSAGE" in signed.stdout


def test_gnupg_non_ascii_passphrase(gnupg, tmp_path):
    phrase = "chiave-è-più-lunga"
    pgp.own_key(ME)
    backup = tmp_path / "backup.asc"
    pgp_backup.export_backup(backup, phrase)
    assert gnupg.gpg("--import", str(backup)).returncode == 0
    cipher = gnupg.encrypt_to(ME, b"hello")
    assert gnupg.plaintext(cipher, phrase) == b"hello"


def test_gnupg_decrypts_with_a_gigamail_key_imported_unprotected(gnupg, tmp_path):
    """Control for the tests above: the same key without our protection.
    When this one fails too, GnuPG cannot use the key itself and the
    passphrase protection is not the cause."""
    key = pgp.own_key(ME)
    plain = tmp_path / "plain.pgp"
    plain.write_bytes(bytes(key))
    done = gnupg.gpg("--import", str(plain))
    assert done.returncode == 0, done.stderr
    cipher = gnupg.encrypt_to(ME, b"hello")
    assert gnupg.plaintext(cipher, "") == b"hello"


def test_gnupg_reads_back_its_own_protected_export(gnupg, tmp_path):
    """Control with no GigaMail code in it: a curve key GnuPG made and
    exported with a passphrase, imported into another GnuPG home the way a
    backup is (in batch, still protected), then used to decrypt."""
    made = gnupg.generate(ME, "ed25519", PASSPHRASE)
    if made.returncode != 0:
        _unavailable("GnuPG cannot generate ed25519 here: "
                     + made.stderr.decode("utf-8", "replace")[:200])
    exported = tmp_path / "from-gnupg.asc"
    exported.write_bytes(gnupg.export_secret(ME, PASSPHRASE))
    other = Gnupg(gnupg.exe, tempfile.mkdtemp(prefix="gm"))
    try:
        done = other.gpg("--import", str(exported))
        assert done.returncode == 0, done.stderr
        cipher = other.encrypt_to(ME, b"hello")
        assert other.plaintext(cipher, PASSPHRASE) == b"hello"
    finally:
        other.close()


@pytest.mark.parametrize("algo,passphrase", [("ed25519", PASSPHRASE),
                                             ("rsa3072", PASSPHRASE),
                                             ("ed25519", "")])
def test_a_key_exported_by_gnupg_is_restored(gnupg, tmp_path, algo, passphrase):
    """Generated and exported by GnuPG, with a passphrase or without one;
    GigaMail restores it, opens a mail GnuPG encrypted to it and backs it
    up again."""
    made = gnupg.generate(ME, algo, passphrase)
    if made.returncode != 0:
        _unavailable(f"this GnuPG cannot generate {algo}: "
                     + made.stderr.decode("utf-8", "replace")[:200])
    exported = tmp_path / "from-gnupg.asc"
    exported.write_bytes(gnupg.export_secret(ME, passphrase))
    packets = pgp_backup._dearmor(exported.read_bytes())
    assert pgp_backup.is_protected(packets) == bool(passphrase)
    out = pgp_backup.import_backup(exported, passphrase or None)
    assert [o["outcome"] for o in out] == ["active"]
    mail = _pgp_mime(gnupg.encrypt_to(ME, _inner_mime("hello")))
    info = pgp.open_message(mail, ME)[1]
    assert info["decrypted"], info["error"]
    pgp_backup.export_backup(tmp_path / "again.asc", PASSPHRASE)


def test_mail_between_two_gigamail_keys_is_not_readable_by_gnupg_2_4(gnupg, tmp_path):
    """Documents a declared limit (SECURITY.md): with only GigaMail keys as
    recipients the library uses the newest packet format. If this test
    starts failing because GnuPG reads the mail, the limit is gone: update
    SECURITY.md and turn the assertion around."""
    pgp.own_key(ME)
    peer = pysequoia.Tsk.generate(user_id=f"<{PEER}>")
    pgp.import_peer_key(PEER, bytes(peer.extract_certificate()))
    mail = pgp.encrypt_message(_clear_mail(), ME, [PEER])
    backup = tmp_path / "backup.asc"
    pgp_backup.export_backup(backup, PASSPHRASE)
    assert gnupg.gpg("--import", str(backup)).returncode == 0
    result = gnupg.decrypt(pgp._ciphertext(mail), PASSPHRASE)
    if gnupg.version >= (2, 5):
        pytest.skip("measured on GnuPG 2.4 only")
    assert result.returncode != 0
    assert b"confidential terms" not in result.stdout + result.stderr
    # it fails on the packet version, not on the key or the passphrase
    assert re.search(r"packet\(\d+\) with unknown version",
                     result.stderr.decode("utf-8", "replace")), result.stderr
    assert pgp.open_message(mail, ME)[1]["decrypted"]      # GigaMail reads it

