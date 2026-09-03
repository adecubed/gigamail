"""La classe Watcher: orchestra i moduli del package, un tick alla volta.

I metodi sono deleghe sottili: la logica vive nei moduli per
responsabilita' (ingestion, pipeline, execution, telegram, process_state).
I nomi con underscore restano perche' test e console li chiamano.
"""
from typing import Any, Dict, List, Optional

from ade_mail_agent import policy
from ade_mail_agent.core import rules as rules_mod
from ade_mail_agent.core import telegram_channel

from . import execution, ingestion, pipeline, process_state, telegram
from .log import _log


class Watcher:
    _PIN_MAX_FAILS = telegram._PIN_MAX_FAILS
    _PIN_LOCK_SECONDS = telegram._PIN_LOCK_SECONDS

    def __init__(self, interval: int = 60, verbose: bool = False,
                 unread_days: int = 2, unread_top: int = 25):
        self.interval = max(int(interval), 10)
        self.verbose = verbose
        self.unread_days = unread_days
        self.unread_top = unread_top

    # -- fase A: eseguire le semi approvate nel frattempo ------------------

    def execute_approved(self) -> int:
        return execution.execute_approved(self)

    # -- fase B: posta nuova → regole -------------------------------------

    def _poll_folder(self, rule: Dict[str, Any]) -> List[Dict[str, Any]]:
        return ingestion.poll_folder(rule, top=self.unread_top,
                                     unread_days=self.unread_days,
                                     verbose=self.verbose)

    @staticmethod
    def _matches(rule: Dict[str, Any], message: Dict[str, Any]) -> bool:
        return ingestion.matches(rule, message)

    def _folder_of(self, rule: Dict[str, Any]) -> str:
        return ingestion.folder_of(rule)

    def process_message(self, rule: Dict[str, Any], message: Dict[str, Any],
                        retry_feedback: Optional[str] = None,
                        previous_body: Optional[str] = None) -> str:
        return pipeline.process_message(self, rule, message,
                                        retry_feedback=retry_feedback,
                                        previous_body=previous_body)

    def process_retries(self) -> int:
        return execution.process_retries(self)

    def heartbeat(self) -> None:
        process_state.heartbeat(self.interval)

    def tick(self) -> Dict[str, int]:
        stats = {"executed": 0, "processed": 0}
        self.heartbeat()
        stats["executed"] = self.execute_approved()
        stats["processed"] += self.process_retries()
        for rule in rules_mod.store().active():
            for message in self._poll_folder(rule):
                if not self._matches(rule, message):
                    continue
                message_id = str(message.get("id"))
                if rules_mod.store().already_handled(rule["rule_id"], message_id):
                    continue
                self.process_message(rule, message)
                stats["processed"] += 1
        return stats

    # -- Telegram: tap e comandi dall'umano --------------------------------

    def _tg_say(self, tg, it: str, en: str) -> None:
        telegram.say(tg, it, en)

    def _tg_approve_allowed(self, tg) -> bool:
        return telegram.approve_allowed(tg)

    def check_telegram_trust(self, tg) -> None:
        telegram.check_trust(tg)

    def handle_telegram_event(self, tg, ev: Dict[str, Any]) -> None:
        telegram.handle_event(self, tg, ev)

    def _tg_action(self, tg, action: str, rid: str, rs,
                   message_id: int = 0) -> None:
        telegram.action(self, tg, action, rid, rs, message_id=message_id)

    def _tg_pin_locked(self, rs) -> int:
        return telegram.pin_locked(rs)

    def _tg_check_pin(self, tg, rid: str, text: str, rs,
                      message_id: int = 0) -> None:
        telegram.check_pin(self, tg, rid, text, rs, message_id=message_id)

    def _tg_retry(self, tg, rid: str, feedback: str, rs) -> None:
        telegram.retry(self, tg, rid, feedback, rs)

    def _wait(self, seconds: int) -> None:
        telegram.wait(self, seconds)

    # -- loop ---------------------------------------------------------------

    def run(self, once: bool = False) -> None:
        tg = telegram_channel.channel()
        # Non basta approve_enabled: l'approvazione da Telegram vale solo
        # se la chat e' stata registrata dietro Hello. Dire "con
        # approvazione" guardando solo il file e' dichiarare attiva una
        # cosa spenta — e lo si scopre premendo Approva e vedendosi
        # rispondere di no.
        approva = bool(tg) and self._tg_approve_allowed(tg)
        _log(f"watcher attivo, intervallo {self.interval}s"
             + (f", Telegram {'con' if approva else 'senza'} approvazione"
                if tg else ""), True)
        if tg and tg.approve_enabled and not approva:
            _log("ATTENZIONE: notify.json chiede l'approvazione da "
                 "Telegram ma nessuna chat e' registrata dietro Hello "
                 "(tg_trusted_chat vuoto): i tap su Approva verranno "
                 "rifiutati. Esegui: gigamail telegram setup --approve",
                 True)
        if tg:
            # Quale chat questo watcher considera "l'umano": scritto
            # nell'audit a ogni avvio, cosi' un notify.json manomesso
            # lascia traccia (SECURITY.md, approvazione da Telegram).
            policy.audit("telegram", {"chat_id": tg.chat_id,
                                      "approve": tg.approve_enabled},
                         "telegram_trusted_chat")
            self.check_telegram_trust(tg)
        while True:
            try:
                stats = self.tick()
                if stats["processed"] or stats["executed"]:
                    _log(f"tick: {stats}", True)
            except KeyboardInterrupt:
                raise
            except Exception as e:
                _log(f"tick fallito: {e}", True)
            if once:
                return
            self._wait(self.interval)
