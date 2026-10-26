# GigaMail — mail for your AI agent
# Copyright (C) 2026 Adecubed
# Licensed under the GNU AGPL v3 or later. See LICENSE.
"""Vecchio nome del package: ora si chiama `gigamail`.

Resta perche' fuori da questo repository ci sono ancora riferimenti al nome
vecchio: configurazioni MCP con `python -m ade_mail_agent.server`, il
protocollo gigamail:// registrato in HKLM come `-m ade_mail_agent.cli`,
script di chi importava i moduli.

Non e' una copia: `ade_mail_agent.X` e' LO STESSO oggetto modulo di
`gigamail.X`. Con due copie ci sarebbero due store, due cache, e un
monkeypatch su uno non vedrebbe l'altro. `python -m ade_mail_agent.cli`
esegue il codice di `gigamail.cli` come __main__, come se si fosse scritto
il nome nuovo.
"""
import importlib
import importlib.abc
import importlib.util
import sys

import gigamail as _gigamail

_VECCHIO = __name__
_NUOVO = "gigamail"

__version__ = _gigamail.__version__
__path__ = []  # e' un package: i sottomoduli li risolve _Alias


def _nuovo(nome: str) -> str:
    return _NUOVO + nome[len(_VECCHIO):]


class _Alias(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def find_spec(self, fullname, path=None, target=None):
        if not fullname.startswith(_VECCHIO + "."):
            return None
        spec = importlib.util.find_spec(_nuovo(fullname))
        if spec is None:
            return None
        return importlib.util.spec_from_loader(
            fullname, self,
            is_package=spec.submodule_search_locations is not None)

    def create_module(self, spec):
        return importlib.import_module(_nuovo(spec.name))

    def exec_module(self, module):
        pass  # gia' eseguito come gigamail.*

    def get_code(self, fullname):
        """Per `python -m ade_mail_agent.X`: runpy chiede il codice e lo
        esegue come __main__."""
        nuovo = _nuovo(fullname)
        spec = importlib.util.find_spec(nuovo)
        return spec.loader.get_code(nuovo)


if not any(isinstance(f, _Alias) for f in sys.meta_path):
    sys.meta_path.insert(0, _Alias())
