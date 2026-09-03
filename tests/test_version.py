"""La versione dichiarata dal pacchetto e' quella di pyproject.toml.

La console ha gia' il suo sync (console/sync-version.js); questo test
chiude l'altro lato: `ade_mail_agent.__version__` non e' piu' una stringa
a mano che resta indietro."""
import re
from pathlib import Path

import ade_mail_agent


def test_version_segue_pyproject():
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    m = re.search(r'^version\s*=\s*"([^"]+)"', pyproject.read_text(encoding="utf-8"), re.M)
    assert m, "version non trovata in pyproject.toml"
    assert ade_mail_agent.__version__ == m.group(1)


def test_health_riporta_la_versione(monkeypatch):
    """La console (e lo smoke test dell'app installata) leggono la versione
    del backend da /health: deve essere quella del pacchetto."""
    import importlib

    from fastapi.testclient import TestClient

    monkeypatch.setenv("ADE_CONSOLE_TOKEN", "tok-v")
    from ade_mail_agent import http_api
    importlib.reload(http_api)
    with TestClient(http_api.app) as c:
        r = c.get("/health", headers={"X-ADE-Token": "tok-v"})
    monkeypatch.delenv("ADE_CONSOLE_TOKEN")
    importlib.reload(http_api)
    assert r.status_code == 200
    assert r.json()["version"] == ade_mail_agent.__version__
