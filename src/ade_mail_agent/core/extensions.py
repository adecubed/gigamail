# GigaMail — mail for your AI agent
# Copyright (C) 2026 Adecubed
# Licensed under the GNU AGPL v3 or later. See LICENSE.
"""Estensioni: cio' che serve a un mestiere, fuori dal core.

Il pacchetto gigamail fa posta: account, indice, ricerca, invio a due
fasi, calendario, documenti, audit. Le regole di un settore (le tipologie
degli appartamenti, i codici delle unita') vivono in pacchetti a parte,
installati con pip e ACCESI esplicitamente. Chi installa gigamail non si
porta dietro lo studio di nessuno.

Due tipi di estensione:
  - pacchetti esterni, trovati per entry point nel gruppo
    `gigamail.extensions` (es. extras/real_estate);
  - funzioni del pacchetto spente di default (BUILTIN): esistono nel
    codice ma non girano finche' qualcuno non le accende.

Si accendono con `gigamail extensions enable NOME` (salvato nello store
delle regole) o con GIGAMAIL_EXTENSIONS=nome1,nome2, che ha la precedenza.

Fail-closed: un'estensione accesa che non si carica non viene saltata in
silenzio. Il suo controllo mancherebbe senza che nessuno lo sappia, e la
bozza partirebbe come se fosse stata verificata. `active()` solleva
ExtensionError e il watcher lascia la mail all'umano.
"""
import logging
import os
from dataclasses import dataclass
from typing import Dict, List, Optional, Set

from ade_mail_agent.agent_bridge import AgentUnavailable

logger = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "gigamail.extensions"
ENV = "GIGAMAIL_EXTENSIONS"
_KV = "extensions"
_KV_MIGRATED = "extensions_migrated"

# Funzioni del pacchetto che partono spente.
#   appointments  mail -> calendario: ogni mail inviata passa dall'agente
#                 per cercare un appuntamento, le risposte dei clienti sui
#                 thread seguiti arrivano su Telegram.
BUILTIN = {"appointments"}


class ExtensionError(AgentUnavailable):
    """Un'estensione accesa non si carica.

    E' un AgentUnavailable perche' ha lo stesso effetto: la bozza verificata
    non si puo' produrre. Il watcher riprova ai giri successivi (magari nel
    frattempo qualcuno la installa) e poi avvisa l'umano; nessuna bozza
    parte senza il controllo che l'utente ha acceso."""


@dataclass
class DraftCheck:
    """Esito del controllo di una bozza.

    ok        la bozza va bene
    detail    cosa non va, per log e audit
    feedback  cosa dire all'agente per riscriverla
    notice    avviso per l'umano se sbaglia anche la riscrittura,
              {"it": ..., "en": ...}; il segnaposto {sender} e' il mittente
    """
    ok: bool
    detail: str = ""
    feedback: str = ""
    notice: Optional[Dict[str, str]] = None


class Extension:
    """Base di un'estensione. Ogni aggancio e' facoltativo."""

    name = ""

    def draft_constraint(self, subject: str, body: str) -> str:
        """Testo aggiunto alle regole del prompt della bozza automatica."""
        return ""

    def check_draft(self, subject: str, body: str,
                    draft: str) -> Optional[DraftCheck]:
        """Verifica la bozza prima che arrivi all'umano. None = nessun parere."""
        return None

    def cited_codes(self, text: str) -> List[str]:
        """I codici di documento nominati nel testo (A.3.2, SKU-12...),
        in ordine: decidono quali file della knowledge si allegano."""
        return []


def _store():
    from ade_mail_agent.core import rules as rules_mod
    return rules_mod.store()


def _migra_una_volta(rs) -> None:
    """Chi usava gia' gli appuntamenti prima che diventassero opzionali li
    ritrova accesi: spegnerli in silenzio vorrebbe dire conferme dei
    clienti che non arrivano piu' in agenda. Si guarda una volta sola."""
    if rs.kv_get(_KV_MIGRATED, "") == "1":
        return
    try:
        from ade_mail_agent.core.data_paths import app_root
        if (app_root() / ".appointments.db").exists() and not rs.kv_get(_KV, ""):
            rs.kv_set(_KV, "appointments")
    finally:
        rs.kv_set(_KV_MIGRATED, "1")


def _parse(valore: str) -> Set[str]:
    return {p.strip().lower() for p in str(valore or "").split(",") if p.strip()}


def enabled_names() -> Set[str]:
    env = os.environ.get(ENV)
    if env is not None:
        return _parse(env)
    try:
        rs = _store()
        _migra_una_volta(rs)
        return _parse(rs.kv_get(_KV, ""))
    except Exception as e:
        logger.warning("estensioni non leggibili: %s", e)
        return set()


def enabled(name: str) -> bool:
    return name.lower() in enabled_names()


def set_enabled(name: str, on: bool) -> Set[str]:
    rs = _store()
    _migra_una_volta(rs)
    nomi = _parse(rs.kv_get(_KV, ""))
    (nomi.add if on else nomi.discard)(name.lower())
    rs.kv_set(_KV, ",".join(sorted(nomi)))
    return nomi


def available() -> Dict[str, str]:
    """Nome -> provenienza: le BUILTIN e gli entry point installati."""
    out = {n: "builtin" for n in sorted(BUILTIN)}
    for ep in _entry_points():
        out[ep.name.lower()] = ep.value
    return out


def _entry_points():
    from importlib.metadata import entry_points
    try:
        return list(entry_points(group=ENTRY_POINT_GROUP))
    except TypeError:  # Python < 3.10 non accetta group=
        return list(entry_points().get(ENTRY_POINT_GROUP, []))


_cache: Dict[str, Extension] = {}


def active() -> List[Extension]:
    """Le estensioni esterne accese, caricate. Solleva ExtensionError se
    una di quelle accese non c'e' o non si importa."""
    nomi = enabled_names() - BUILTIN
    if not nomi:
        return []
    punti = {ep.name.lower(): ep for ep in _entry_points()}
    out: List[Extension] = []
    for nome in sorted(nomi):
        if nome in _cache:
            out.append(_cache[nome])
            continue
        ep = punti.get(nome)
        if ep is None:
            raise ExtensionError(f"estensione '{nome}' accesa ma non installata")
        try:
            obj = ep.load()
            ext = obj() if isinstance(obj, type) else obj
        except Exception as e:
            raise ExtensionError(f"estensione '{nome}' non caricabile: {e}") from e
        ext.name = ext.name or nome
        _cache[nome] = ext
        out.append(ext)
    return out


def register(ext: Extension) -> None:
    """Per i test: un'estensione caricata senza entry point."""
    _cache[ext.name.lower()] = ext


def reset() -> None:
    _cache.clear()
