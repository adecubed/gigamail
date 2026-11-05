"""The user hears, once, that a reply rule is about to expire or has.

An expired rule answers nothing and used to say nothing: an office found
out a month later, from the mail that went unanswered."""
import time

import pytest

from gigamail import policy
from gigamail.core import rules as rules_mod
from gigamail.watcher import rule_expiry


@pytest.fixture()
def store(tmp_path, monkeypatch):
    s = rules_mod.RuleStore(tmp_path / "rules.db")
    sent = []
    monkeypatch.setattr(policy, "notify_approval_requested",
                        lambda rid, tool, preview, message=None, **kw: sent.append((tool, message)))
    monkeypatch.setattr(policy, "audit", lambda *a, **k: None)
    s.sent = sent
    return s


def _mk(store, days, **kw):
    return store.create(account_id=1, trigger_kind="senders",
                        trigger_values=["mario.rossi@example.com"], reply_style="",
                        doc_paths=[], mode="semi", created_by="test",
                        hello_verified_at=time.time(), expiry_days=days, **kw)


def test_expiring_rule_is_told_once_with_how_to_renew(store):
    rid = _mk(store, 2)
    _mk(store, 30)
    assert rule_expiry.tick(store) == 1
    tool, message = store.sent[0]
    assert tool == f"rule_expiry:{rid}"
    assert f"gigamail rules renew {rid}" in message
    assert rule_expiry.tick(store) == 0, "told twice"


def test_expiry_day_is_told_again_and_a_renewal_warns_the_next_period(store):
    rid = _mk(store, 2)
    rule_expiry.tick(store)
    later = store.get(rid)["expires_at"] + 60
    assert rule_expiry.tick(store, now=later) == 1      # it has now expired
    assert rule_expiry.tick(store, now=later) == 0
    store.renew(rid, time.time())
    renewed = store.get(rid)["expires_at"]
    assert rule_expiry.tick(store, now=renewed - 86400) == 1


def test_paused_and_long_expired_rules_are_not_news(store):
    store.pause(_mk(store, 1), "manual")
    _mk(store, -30)
    assert rule_expiry.tick(store) == 0


def test_a_broken_store_does_not_stop_the_watcher(store, monkeypatch):
    monkeypatch.setattr(store, "list_all", lambda: 1 / 0)
    assert rule_expiry.tick(store) == 0
