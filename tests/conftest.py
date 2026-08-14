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
os.environ.pop("ADE_AGENT_CMD", None)
os.environ.pop("ADE_CONSOLE_TOKEN", None)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import ade_mail_agent  # noqa: E402,F401 — attiva lo shim per core/

import pytest  # noqa: E402


@pytest.fixture()
def tmp_ade_root():
    """Percorso della finta %APPDATA%/ADE usata dai test."""
    return _TMP / "ADE"
