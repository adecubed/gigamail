"""RuleStore (0.2): le regole nascono solo dietro verifica umana, hanno
scadenza e tetti, e la memoria (handled) regge idempotenza, cooldown,
tetto giornaliero e finestra di raffica."""
import time

import pytest

from gigamail.core import rules as rules_mod


@pytest.fixture()
def store(tmp_path):
    return rules_mod.RuleStore(tmp_path / "rules.db")


def _mk(store, **kw):
    args = dict(account_id=1, trigger_kind="senders",
                trigger_values=["cliente@fidato.it"], reply_style="cordiale",
                doc_paths=[], mode="semi", created_by="test",
                hello_verified_at=time.time())
    args.update(kw)
    return store.create(**args)


def test_regola_senza_hello_rifiutata(store):
    with pytest.raises(ValueError, match="hello_verified_at"):
        _mk(store, hello_verified_at=0.0)


def test_validazioni(store):
    with pytest.raises(ValueError):
        _mk(store, trigger_kind="everything")
    with pytest.raises(ValueError):
        _mk(store, mode="yolo")
    with pytest.raises(ValueError):
        _mk(store, trigger_values=[])


def test_create_e_get(store):
    rid = _mk(store, mode="auto", doc_paths=["C:/x/listino.pdf"])
    r = store.get(rid)
    assert r["mode"] == "auto"
    assert r["trigger_values"] == ["cliente@fidato.it"]
    assert r["doc_paths"] == ["C:/x/listino.pdf"]
    assert r["first_contact"] == "semi"  # default prudente
    assert not r["paused"] and not r["expired"]


def test_scadenza_obbligatoria_ed_esclusione(store):
    rid = _mk(store, expiry_days=-1)  # gia' scaduta
    assert store.get(rid)["expired"]
    assert rid not in {r["rule_id"] for r in store.active()}


def test_pause_libera_resume_solo_con_hello(store):
    rid = _mk(store)
    assert store.pause(rid, "raffica")
    assert store.get(rid)["paused"]
    assert rid not in {r["rule_id"] for r in store.active()}
    with pytest.raises(ValueError):
        store.resume(rid, 0.0)
    assert store.resume(rid, time.time())
    assert not store.get(rid)["paused"]


def test_handled_idempotenza_e_contatori(store):
    rid = _mk(store)
    assert not store.already_handled(rid, "m1")
    store.record(rid, 1, "m1", "a@b.it", "sent")
    assert store.already_handled(rid, "m1")
    assert store.sent_today(rid) == 1
    assert store.last_reply_to(rid, "A@B.IT") is not None  # case-insensitive
    assert store.matches_since(rid, time.time() - 60) == 1
    assert store.ever_replied_to("a@b.it", 1)
    assert not store.ever_replied_to("altro@b.it", 1)


def test_delete_pulisce_anche_handled(store):
    rid = _mk(store)
    store.record(rid, 1, "m1", "a@b.it", "sent")
    assert store.delete(rid)
    assert store.get(rid) is None
    assert not store.already_handled(rid, "m1")


def test_first_start_builds_one_store_however_many_threads_ask(tmp_path, monkeypatch):
    """On a fresh profile the watcher guard thread and GET /onboarding
    reach store() together, and each built a RuleStore on the same new
    rules.db: the likely cause of the 500 that kept the first-run guide
    shut in the desktop build (26/10). One store, built once."""
    import threading

    built = []
    real_init = rules_mod.RuleStore.__init__

    def slow_init(self, path=None):
        built.append(self)
        time.sleep(0.05)          # widen the window two threads raced through
        real_init(self, tmp_path / "rules.db")

    monkeypatch.setattr(rules_mod.RuleStore, "__init__", slow_init)
    monkeypatch.setattr(rules_mod, "_store", None)
    go = threading.Barrier(8)
    got = []

    def ask():
        go.wait()
        got.append(rules_mod.store())

    threads = [threading.Thread(target=ask) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(built) == 1
    assert all(s is got[0] for s in got)


# ── expiry: renewing, and knowing it is near ───────────────────────

def test_renew_gives_another_period_of_the_rule_own_length(store):
    rid = _mk(store, expiry_days=10)
    store.pause(rid, "manual")
    with pytest.raises(ValueError):
        store.renew(rid, 0.0)
    before = time.time()
    expires_at = store.renew(rid, time.time())
    assert before + 10 * 86400 - 5 <= expires_at <= time.time() + 10 * 86400
    rule = store.get(rid)
    assert rule["expires_at"] == expires_at and rule["expiry_days"] == 10
    assert rule["paused"], "renewing is not resuming"
    assert store.renew("rule_missing", time.time()) is None


def test_an_expired_rule_can_be_renewed(store):
    rid = _mk(store, expiry_days=-1)
    assert store.get(rid)["expired"]
    store.renew(rid, time.time())
    rule = store.get(rid)
    assert not rule["expired"] and rid in {r["rule_id"] for r in store.active()}


def test_a_rule_made_before_its_length_was_kept_renews_for_that_length(store):
    rid = _mk(store, expiry_days=20)
    with store._conn() as conn:
        conn.execute("UPDATE rules SET expiry_days=NULL WHERE rule_id=?", (rid,))
    assert store.get(rid)["expiry_days"] == 20


def test_expiring_marks_the_last_days(store):
    soon = _mk(store, expiry_days=rules_mod.EXPIRY_WARNING_DAYS - 1)
    later = _mk(store, expiry_days=rules_mod.EXPIRY_WARNING_DAYS + 5)
    gone = _mk(store, expiry_days=-1)
    assert store.get(soon)["expiring"]
    assert not store.get(later)["expiring"]
    assert not store.get(gone)["expiring"] and store.get(gone)["expired"]
