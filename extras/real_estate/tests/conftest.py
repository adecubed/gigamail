"""Stesso isolamento della suite del core: dati in una cartella temporanea,
nessun prompt Hello vero, nessun toast. L'estensione e' accesa per tutti i
test di questa cartella."""
import os
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="gigamail-re-tests-"))
(_TMP / "ADE").mkdir(parents=True, exist_ok=True)
os.environ["APPDATA"] = str(_TMP)
os.environ["ADE_ROOT"] = str(_TMP / "ADE")
for _name in ("GIGAMAIL_ROOT", "GIGAMAIL_DATA_DIR", "ADE_MAIL_DATA_DIR",
              "ADE_AGENT_CMD", "ADE_CONSOLE_TOKEN"):
    os.environ.pop(_name, None)
os.environ["GIGAMAIL_CONSENT_BACKEND"] = "deny"
os.environ["GIGAMAIL_NOTIFY_DESKTOP"] = "0"
os.environ["GIGAMAIL_LANG"] = "it"
os.environ["GIGAMAIL_EXTENSIONS"] = "real_estate"

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _real_estate_acceso(monkeypatch):
    from ade_mail_agent.core import extensions
    monkeypatch.setenv("GIGAMAIL_EXTENSIONS", "real_estate")
    extensions.reset()
    yield
    extensions.reset()
