"""Config comune dei test GigaMail.

CRITICO: i moduli core calcolano i percorsi dati (APPDATA/ADE) al momento
dell'import, quindi l'ambiente va isolato PRIMA di importare qualunque
modulo del progetto. Questo conftest viene importato da pytest prima dei
moduli di test: qui ridirigiamo APPDATA e ADE_ROOT su una cartella
temporanea di sessione, poi attiviamo lo shim sys.path del package.
"""
import os
import sys
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="gigamail-tests-"))
(_TMP / "ADE").mkdir(parents=True, exist_ok=True)
os.environ["APPDATA"] = str(_TMP)
os.environ["ADE_ROOT"] = str(_TMP / "ADE")
# Installed clients may set newer overrides, which take precedence over
# ADE_ROOT/APPDATA. Never let a test session inherit production data paths.
for _name in ("GIGAMAIL_ROOT", "GIGAMAIL_DATA_DIR", "ADE_MAIL_DATA_DIR"):
    os.environ.pop(_name, None)
os.environ.pop("ADE_AGENT_CMD", None)
os.environ.pop("ADE_CONSOLE_TOKEN", None)
# La suite non deve MAI aprire un prompt Windows Hello / Touch ID vero sul
# PC di chi la lancia: il consenso e' negato di default. I test che vogliono
# un "si'" lo chiedono esplicitamente con allow + ADE_MAIL_DRYRUN.
os.environ["GIGAMAIL_CONSENT_BACKEND"] = "deny"
# ...e non deve nemmeno far comparire toast di sistema sul suo desktop.
os.environ["GIGAMAIL_NOTIFY_DESKTOP"] = "0"
# Lingua delle notifiche pinnata: la suite deve dare lo stesso esito sul
# PC italiano di Paolo e sui runner CI in inglese.
os.environ["GIGAMAIL_LANG"] = "it"
# Nessuna estensione accesa di default: la suite prova il core nudo. I test
# che ne vogliono una la accendono con le fixture qui sotto.
os.environ["GIGAMAIL_EXTENSIONS"] = ""

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import pytest  # noqa: E402

import gigamail  # noqa: E402,F401 — attiva lo shim per core/


@pytest.fixture(autouse=True)
def _estensioni_pulite(monkeypatch):
    from gigamail.core import extensions
    monkeypatch.setenv("GIGAMAIL_EXTENSIONS", "")
    extensions.reset()
    yield
    extensions.reset()


@pytest.fixture()
def appointments_on(monkeypatch):
    """Gli appuntamenti (mail -> calendario) accesi."""
    monkeypatch.setenv("GIGAMAIL_EXTENSIONS", "appointments")


@pytest.fixture()
def estensione(monkeypatch):
    """Accende un'estensione di prova senza installarla: estensione(obj)."""
    from gigamail.core import extensions

    def accendi(ext):
        extensions.register(ext)
        attuali = [n for n in os.environ.get("GIGAMAIL_EXTENSIONS", "").split(",") if n]
        monkeypatch.setenv("GIGAMAIL_EXTENSIONS", ",".join(attuali + [ext.name]))
        return ext
    return accendi


@pytest.fixture()
def tmp_ade_root():
    """Percorso della finta %APPDATA%/ADE usata dai test."""
    return _TMP / "ADE"


@pytest.fixture()
def account_signature(monkeypatch):
    """Per-account signatures kept in memory: account_signature(aid, text)."""
    from gigamail.core import signature
    settings = {}
    monkeypatch.setattr(signature.accounts, "get_setting",
                        lambda key, default="": settings.get(key, default))
    monkeypatch.setattr(signature.accounts, "set_setting",
                        lambda key, value: settings.__setitem__(key, str(value)))

    def put(account_id, text):
        return signature.save(account_id, text)
    put.settings = settings
    return put
