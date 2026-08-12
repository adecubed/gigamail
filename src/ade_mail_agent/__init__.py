"""ADE Mail Agent — server MCP per la posta del tuo agente.

I moduli in `core/` provengono dal backend ADE Mail e si importano
tra loro con nomi piatti (`import accounts`), quindi la cartella core
va messa sul sys.path prima di qualunque import da lì.
Debito tecnico noto: convertirli a import relativi di package.
"""
import sys
from pathlib import Path

_CORE = str(Path(__file__).resolve().parent / "core")
if _CORE not in sys.path:
    sys.path.insert(0, _CORE)

__version__ = "0.1.0"
