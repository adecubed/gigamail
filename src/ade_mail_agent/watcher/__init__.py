# GigaMail — mail for your AI agent
# Copyright (C) 2026 Adecubed
# Licensed under the GNU AGPL v3 or later. See LICENSE.
"""`gigamail watch` — il processo che innesca le regole di risposta (0.2).

Il server MCP resta passivo: e' questo processo (CLI, avviabile anche dalla
console) che vede la posta nuova, la passa dalle barriere anti-spam
(mail_guard), fa scrivere la bozza all'agente DELL'UTENTE (agent_bridge) e
crea la richiesta di approvazione:

  semi  la richiesta nasce pending e viene notificata (B5): l'umano approva
        con Windows Hello / Touch ID da console o CLI; al giro successivo
        il watcher la vede approvata e la esegue.
  auto  la richiesta nasce gia' approvata, decided_by "automode:<rule_id>".
        La pre-approvazione E' la regola: l'umano l'ha data dietro Hello
        alla creazione, con scadenza e tetto. La notifica parte comunque,
        a posteriori.

Proprieta' non negoziabili (design 20/08, NOTES):
  - INDIRIZZAMENTO FISSO: il drafter produce SOLO il corpo. Destinatario,
    thread e subject li fissa mail_router.reply_message dal messaggio in
    arrivo — sempre e solo il From, mai il Reply-To, mai indirizzi usciti
    dalla bozza. Un'injection nel corpo non ha canale d'uscita.
  - CONTENUTO PER-REGOLA: nel prompt entrano solo i documenti dichiarati
    nella regola. Niente knowledge globale, niente ricerca in posta.
  - FAIL-CLOSED: header non leggibili, DMARC non-pass, primo contatto →
    al massimo semi. Raffica di match → la regola si pausa da sola.

Struttura del package (una responsabilita' per modulo):

  ingestion      posta recente della cartella della regola + match
  drafting       prompt e bozza dall'agente (solo corpo)
  addressing     destinatario dal corpo (relay) e oggetto "Re:"
  approvals      richiesta di approvazione, preview, esecuzione at-most-once
  notify         testi delle notifiche (toast / Telegram)
  pipeline       una mail matchata, dal burst-check alla decisione
  execution      esegue le approvate, riprocessa i retry chiesti dall'umano
  telegram       tap e comandi dal telefono, long-poll tra un tick e l'altro
  process_state  pid / heartbeat / running_state per console e CLI
  runner         la classe Watcher che orchestra tutto

Questo modulo e' la facciata: CLI, console e test importano da qui.
"""
from ade_mail_agent.core import rules as rules_mod

from .addressing import _reply_subject, body_reply_address
from .approvals import (
    _RULE_TTL_SECONDS,
    TOOL,
    _create_request,
    _execute_reply,
    _preview_for,
)
from .drafting import (
    _DRAFT_ATTEMPTS,
    _DRAFT_TIMEOUT_SECONDS,
    build_draft_prompt,
    draft_reply,
)
from .log import _log
from .notify import _auto_notify_text, _semi_notify_text
from .process_state import pid_alive, running_state
from .runner import Watcher

__all__ = [
    "TOOL", "Watcher", "body_reply_address", "build_draft_prompt", "draft_reply",
    "pid_alive", "running_state", "rules_mod",
    "_DRAFT_ATTEMPTS", "_DRAFT_TIMEOUT_SECONDS", "_RULE_TTL_SECONDS",
    "_auto_notify_text", "_create_request", "_execute_reply", "_log",
    "_preview_for", "_reply_subject", "_semi_notify_text",
]
