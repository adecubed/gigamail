"""Log del watcher.

Due canali con due destinatari:
  _log     → stdout, con prefisso [watch]: e' cio' che l'umano legge
             (la console lo ridirige in watch.log). Solo se verbose,
             tranne per gli eventi che deve vedere comunque.
  logger   → logging standard ("gigamail.watcher"): i fallimenti
             best-effort che prima finivano in `except: pass`. Silenzioso
             finche' nessuno configura il logging, ma mai piu' invisibile.
"""
import logging

logger = logging.getLogger("gigamail.watcher")


def _log(msg: str, verbose: bool) -> None:
    if verbose:
        print(f"[watch] {msg}")
