"""La risposta deve riguardare la tipologia che il cliente ha chiesto.

27 settembre 2026: un cliente scrive per un BILOCALE e riceve tre
trilocali da 379.000 euro in su, planimetrie comprese. Gli allegati erano
coerenti col testo; era il testo a rispondere alla domanda sbagliata,
ricopiato dalla risposta precedente che il prompt gli metteva davanti
come "template suggerito".
"""
import time

import pytest

from ade_mail_agent import agent_bridge, policy
from ade_mail_agent import watcher as watcher_mod
from ade_mail_agent.core import attachments, mail_router, tipologie
from ade_mail_agent.core import rules as rules_mod

OGGETTO_BILO = ("Nuovo messaggio di Marco Neri sul tuo immobile, Bilocale in "
                "Via Treviglio, 28, Precotto, Milano")
OGGETTO_TRILO = ("Nuovo messaggio di Chiara sul tuo immobile, Trilocale in "
                 "Via Treviglio, 28, Precotto, Milano")

# La risposta realmente partita a Marco Neri, accorciata.
BOZZA_SBAGLIATA = """Gentile Sig. Neri,

la ringraziamo per il suo interesse per il bilocale in Via Treviglio 28.

- B.1.3: trilocale di 80,43 mq con balcone di 15,21 mq, prezzo 379.000
- A.1.4: trilocale di 83,92 mq con balcone di 10,70 mq, prezzo 382.000
- B.1.4: trilocale di 83,92 mq con balcone di 12,37 mq, prezzo 383.000

In allegato trova le planimetrie delle soluzioni indicate."""

BOZZA_GIUSTA = """Gentile Sig. Neri,

- B.2.1: bilocale di 55,00 mq con balcone di 8,00 mq, prezzo 288.000

Resto a disposizione per un appuntamento in ufficio."""


# ── lettura della tipologia ──────────────────────────────────────────

def test_la_tipologia_si_legge_dall_oggetto():
    assert tipologie.chiesta(OGGETTO_BILO, "") == "bilocale"
    assert tipologie.chiesta(OGGETTO_TRILO, "") == "trilocale"


def test_quadrilocale_non_si_confonde_con_monolocale():
    assert tipologie.chiesta("Quadrilocale in Via Treviglio", "") == "quadrilocale"
    assert tipologie.chiesta("Monolocale in Via Treviglio", "") == "monolocale"


def test_loggetto_vince_sul_corpo():
    """Nel corpo la parola puo' arrivare dalla citazione della nostra
    risposta precedente: l'annuncio guardato davvero e' nell'oggetto."""
    assert tipologie.chiesta(OGGETTO_BILO, "mi avevate scritto dei trilocali") \
        == "bilocale"


def test_nessuna_tipologia_dichiarata():
    assert tipologie.chiesta("Richiesta informazioni", "Buongiorno") is None


# ── coerenza della bozza ─────────────────────────────────────────────

def test_bozza_fuori_tipologia_riconosciuta():
    assert tipologie.elencate(BOZZA_SBAGLIATA) == {"trilocale"}
    assert not tipologie.coerente("bilocale", BOZZA_SBAGLIATA)


def test_bozza_in_tipologia_passa():
    assert tipologie.coerente("bilocale", BOZZA_GIUSTA)


def test_risposta_senza_elenco_non_viene_bloccata():
    """Conferme di appuntamento e risposte interlocutorie non propongono
    appartamenti: non c'e' niente da confrontare."""
    assert tipologie.coerente(
        "bilocale", "Le confermo l'appuntamento di giovedi' alle 17:00.")


def test_senza_tipologia_chiesta_non_si_blocca_nulla():
    assert tipologie.coerente(None, BOZZA_SBAGLIATA)


# ── il watcher non spedisce la risposta ricopiata ────────────────────

def _msg(mid="201", sender="reply@idealista.it", subject=OGGETTO_BILO):
    return {"id": mid, "subject": subject,
            "from": {"emailAddress": {"name": "idealista", "address": sender}},
            "body": {"content": "Ciao, questo appartamento mi interessa. "
                                "Scrivimi a marco.neri@example.com"},
            "isRead": False}


@pytest.fixture(autouse=True)
def isolated(tmp_path):
    policy.set_store(policy.ApprovalStore(tmp_path / "approvals.db"))
    rules_mod.set_store(rules_mod.RuleStore(tmp_path / "rules.db"))
    yield
    policy.set_store(None)
    rules_mod.set_store(None)


@pytest.fixture()
def mondo(monkeypatch):
    stato = {"unread": [], "draft": BOZZA_GIUSTA, "replies": []}
    monkeypatch.setattr(mail_router, "get_messages",
                        lambda **kw: list(stato["unread"]))
    monkeypatch.setattr(mail_router, "get_message_headers",
                        lambda **kw: {"authentication-results":
                                      ["mx; dmarc=pass header.from=idealista.it"]})
    monkeypatch.setattr(
        mail_router, "get_message",
        lambda **kw: next((m for m in stato["unread"]
                           if str(m["id"]) == str(kw.get("message_id"))), {}))
    monkeypatch.setattr(mail_router, "reply_message",
                        lambda **kw: stato["replies"].append(kw) or True)
    monkeypatch.setattr(agent_bridge, "run", lambda prompt, **kw: stato["draft"])
    # Le planimetrie citate esistono: qui si prova la tipologia, non la
    # risoluzione dei file (quella ha i suoi test in test_allegati.py).
    monkeypatch.setattr(
        attachments, "resolve",
        lambda aid, nomi: ([{"name": f"{n}.pdf", "path": f"x/{n}.pdf"}
                            for n in (nomi or [])], []))
    monkeypatch.setattr(attachments, "payload", lambda risolti: [])
    return stato


def _regola():
    return rules_mod.store().create(
        account_id=1, trigger_kind="senders",
        trigger_values=["reply@idealista.it"], reply_style="cordiale",
        doc_paths=[], mode="semi", created_by="test",
        hello_verified_at=time.time())


def test_bozza_con_la_tipologia_sbagliata_non_parte(mondo):
    _regola()
    mondo["draft"] = BOZZA_SBAGLIATA
    mondo["unread"] = [_msg()]
    watcher_mod.Watcher().tick()
    assert policy.store().list_pending() == []
    assert mondo["replies"] == []


def test_bozza_con_la_tipologia_giusta_arriva_allapprovazione(mondo):
    _regola()
    mondo["draft"] = BOZZA_GIUSTA
    mondo["unread"] = [_msg()]
    watcher_mod.Watcher().tick()
    assert len(policy.store().list_pending()) == 1


def test_il_prompt_dichiara_la_tipologia_richiesta():
    rule = rules_mod.store().get(_regola())
    prompt = watcher_mod.build_draft_prompt(rule, 1, _msg())
    assert "TIPOLOGIA RICHIESTA: bilocale" in prompt
    # gli esempi passati sono dichiarati come stile, non come contenuto
    assert "mai al contenuto" in prompt


# ── la bozza sbagliata si riscrive da sola ───────────────────────────

def test_bozza_sbagliata_viene_riscritta_e_arriva_quella_giusta(mondo, monkeypatch):
    """In modalita' semi l'umano deve ricevere la bozza giusta, non un
    avviso: al primo giro l'agente ricopia i trilocali, al secondo, con
    la correzione, propone i bilocali."""
    prompts = []
    bozze = iter([BOZZA_SBAGLIATA, BOZZA_GIUSTA])

    def agente(prompt, **kw):
        prompts.append(prompt)
        return next(bozze)

    monkeypatch.setattr(agent_bridge, "run", agente)
    _regola()
    mondo["unread"] = [_msg()]
    watcher_mod.Watcher().tick()
    pending = policy.store().list_pending()
    assert len(pending) == 1
    assert pending[0]["args"]["body"] == BOZZA_GIUSTA
    # la seconda richiesta all'agente porta la correzione concreta
    assert len(prompts) == 2
    assert "ha scritto per un bilocale" in prompts[1]
    assert "trilocali" in prompts[1]


def test_se_sbaglia_due_volte_si_ferma_e_avvisa(mondo, monkeypatch):
    avvisi = []
    monkeypatch.setattr(policy, "notify_approval_requested",
                        lambda *a, **kw: avvisi.append(kw.get("message") or ""))
    _regola()
    mondo["draft"] = BOZZA_SBAGLIATA
    mondo["unread"] = [_msg()]
    watcher_mod.Watcher().tick()
    assert policy.store().list_pending() == []
    assert mondo["replies"] == []
    assert any("bilocale" in a and "Rispondi a mano" in a for a in avvisi)


def test_la_correzione_dice_cosa_era_sbagliato():
    testo = tipologie.correzione("bilocale", BOZZA_SBAGLIATA)
    assert "trilocali" in testo and "bilocale" in testo
    assert "SOLO bilocali" in testo


def test_vincolo_usa_il_plurale_giusto():
    assert "bilocali disponibili" in tipologie.vincolo("bilocale")
    assert "bilocalei" not in tipologie.vincolo("bilocale")


# ── la bozza automatica non vede le risposte vecchie ────────────────

def test_il_watcher_chiede_allobserver_solo_lo_stile(monkeypatch):
    from ade_mail_agent.core import observer

    chiamate = []
    monkeypatch.setattr(
        observer, "get_context_for_prompt",
        lambda *a, **kw: chiamate.append(kw) or "")
    rule = rules_mod.store().get(_regola())
    watcher_mod.build_draft_prompt(rule, 1, _msg())
    assert chiamate and chiamate[0].get("includi_esempi") is False


def test_observer_senza_esempi_non_restituisce_risposte_vecchie(tmp_path, monkeypatch):
    import sqlite3

    from ade_mail_agent.core import observer

    db = tmp_path / "obs.db"
    monkeypatch.setattr(observer, "DB_PATH", str(db))
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE patterns (account_id INT, pattern_type TEXT,"
                     " pattern_value TEXT, frequency INT)")
        conn.execute("CREATE TABLE interactions (account_id INT, original_draft"
                     " TEXT, final_text TEXT, instruction TEXT, sent_at TEXT)")
        conn.execute("INSERT INTO patterns VALUES (1,'preferred_word','cordialmente',5)")
        conn.execute("INSERT INTO interactions VALUES (1,'x','- B.1.3: trilocale di "
                     "80,43 mq','', '2026-09-27')")
    monkeypatch.setattr(observer, "find_similar_template", lambda *a, **kw: None)
    con = observer.get_context_for_prompt(1, includi_esempi=True)
    senza = observer.get_context_for_prompt(1, includi_esempi=False)
    assert "trilocale" in con
    assert "trilocale" not in senza
    assert "cordialmente" in senza          # lo stile resta

