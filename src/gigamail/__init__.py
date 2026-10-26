"""GigaMail — mail per il tuo agente AI (server MCP + console)."""
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

# Una sola fonte di verita' per la versione: pyproject.toml, letto dai
# metadati del pacchetto installato (anche in editable). Prima qui c'era una
# stringa a mano, rimasta a 0.1.2 mentre il progetto era a 0.3.0.
try:
    __version__ = _pkg_version("gigamail")
except PackageNotFoundError:  # sorgente non installato: mai in produzione
    __version__ = "0.0.0+unknown"
