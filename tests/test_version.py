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
