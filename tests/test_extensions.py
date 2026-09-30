"""Il verticale fuori dal core: estensioni spente finche' non si accendono."""
import time

import pytest

from gigamail.core import appointments, extensions
from gigamail.core import rules as rules_mod


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.delenv("GIGAMAIL_EXTENSIONS", raising=False)
    rules_mod.set_store(rules_mod.RuleStore(tmp_path / "rules.db"))
    yield rules_mod.store()
    rules_mod.set_store(None)


def test_di_default_nessuna_estensione(store, monkeypatch, tmp_path):
    monkeypatch.setattr("gigamail.core.data_paths.app_root", lambda: tmp_path)
    assert extensions.enabled_names() == set()
    assert not extensions.enabled("appointments")
    assert extensions.active() == []


def test_chi_usava_gli_appuntamenti_li_ritrova_accesi(store, monkeypatch, tmp_path):
    """Spegnerli in silenzio con l'aggiornamento vorrebbe dire conferme dei
    clienti che non arrivano piu' in agenda."""
    (tmp_path / ".appointments.db").write_bytes(b"")
    monkeypatch.setattr("gigamail.core.data_paths.app_root", lambda: tmp_path)
    assert extensions.enabled("appointments")
    # la migrazione avviene una volta sola: spenti a mano restano spenti
    extensions.set_enabled("appointments", False)
    assert not extensions.enabled("appointments")


def test_accendere_e_spegnere(store, monkeypatch, tmp_path):
    monkeypatch.setattr("gigamail.core.data_paths.app_root", lambda: tmp_path)
    extensions.set_enabled("Appointments", True)
    assert extensions.enabled("appointments")
    extensions.set_enabled("appointments", False)
    assert extensions.enabled_names() == set()


def test_la_variabile_d_ambiente_vince(store, monkeypatch):
    extensions.set_enabled("appointments", True)
    monkeypatch.setenv("GIGAMAIL_EXTENSIONS", "")
    assert not extensions.enabled("appointments")


def test_accesa_ma_non_installata_solleva(monkeypatch):
    monkeypatch.setenv("GIGAMAIL_EXTENSIONS", "inesistente")
    with pytest.raises(extensions.ExtensionError):
        extensions.active()


def test_le_builtin_non_si_caricano_come_pacchetti(monkeypatch):
    monkeypatch.setenv("GIGAMAIL_EXTENSIONS", "appointments")
    assert extensions.active() == []


def test_invio_con_appuntamenti_spenti_non_chiama_l_agente(monkeypatch):
    """Il core nudo non manda ogni mail inviata all'agente per cercarci un
    appuntamento, e non segue i thread."""
    from gigamail.core import mail_router

    chiamate = []
    monkeypatch.setattr(mail_router, "_send_backend", lambda **kw: {"success": True})
    monkeypatch.setattr(mail_router, "_account", lambda aid=None: {"id": 2})
    monkeypatch.setattr(appointments, "segui", lambda *a: chiamate.append(a))
    monkeypatch.setattr(appointments, "dalla_mail_async", lambda *a: chiamate.append(a))
    esito = mail_router.send_message(account_id=2, to="c@example.com",
                                     subject="Visita", body="martedi' alle 10?")
    assert esito == {"success": True}
    assert chiamate == []


def test_watcher_con_appuntamenti_spenti_non_legge_i_thread(monkeypatch):
    from gigamail import watcher as watcher_mod

    monkeypatch.setattr(appointments, "store",
                        lambda: pytest.fail("store degli appuntamenti aperto"))
    assert watcher_mod.Watcher().sweep_appointments() == 0


def test_cli_enable_chiede_la_verifica(store, monkeypatch, capsys):
    from gigamail import cli

    monkeypatch.setenv("GIGAMAIL_CONSENT_BACKEND", "deny")
    assert cli.main(["extensions", "enable", "appointments"]) == 1
    assert not extensions.enabled("appointments")
    monkeypatch.setenv("GIGAMAIL_CONSENT_BACKEND", "allow")
    monkeypatch.setenv("ADE_MAIL_DRYRUN", "1")
    assert cli.main(["extensions", "enable", "appointments"]) == 0
    assert extensions.enabled("appointments")
    assert cli.main(["extensions", "disable", "appointments"]) == 0
    assert not extensions.enabled("appointments")


def test_cli_enable_rifiuta_i_nomi_sconosciuti(store, monkeypatch):
    from gigamail import cli

    monkeypatch.setenv("GIGAMAIL_CONSENT_BACKEND", "allow")
    monkeypatch.setenv("ADE_MAIL_DRYRUN", "1")
    assert cli.main(["extensions", "enable", "boh"]) == 1


# ── il controllo delle bozze nel watcher ────────────────────────────

class _Vieta(extensions.Extension):
    """Respinge le bozze che contengono una parola."""

    def __init__(self, name, parola):
        self.name, self.parola = name, parola

    def draft_constraint(self, subject, body):
        return f"NON SCRIVERE: {self.parola}"

    def check_draft(self, subject, body, draft):
        if self.parola in draft:
            return extensions.DraftCheck(ok=False, detail=f"c'e' {self.parola}",
                                         feedback=f"togli {self.parola}")
        return extensions.DraftCheck(ok=True)


@pytest.fixture()
def mondo(tmp_path, monkeypatch):
    from gigamail import agent_bridge, policy
    from gigamail.core import mail_router

    policy.set_store(policy.ApprovalStore(tmp_path / "approvals.db"))
    rules_mod.set_store(rules_mod.RuleStore(tmp_path / "rules.db"))
    stato = {"bozze": [], "prompt": [], "avvisi": []}
    msg = {"id": "1", "subject": "Preventivo", "isRead": False,
           "from": {"emailAddress": {"name": "C", "address": "c@fidato.it"}},
           "body": {"content": "Buongiorno"}}
    monkeypatch.setattr(mail_router, "get_messages", lambda **kw: [msg][kw.get("skip", 0):])
    monkeypatch.setattr(mail_router, "get_message_headers", lambda **kw: {
        "authentication-results": ["mx; dmarc=pass header.from=fidato.it"]})
    monkeypatch.setattr(mail_router, "get_message", lambda **kw: msg)
    monkeypatch.setattr(mail_router, "reply_message", lambda **kw: True)

    def agente(prompt, **kw):
        stato["prompt"].append(prompt)
        return stato["bozze"].pop(0)
    monkeypatch.setattr(agent_bridge, "run", agente)
    monkeypatch.setattr(policy, "notify_approval_requested",
                        lambda *a, **kw: stato["avvisi"].append(kw.get("message", "")))
    rules_mod.store().create(
        account_id=1, trigger_kind="senders", trigger_values=["c@fidato.it"],
        reply_style="cordiale", doc_paths=[], mode="semi", created_by="test",
        hello_verified_at=time.time())
    yield stato
    policy.set_store(None)
    rules_mod.set_store(None)


def _pending():
    from gigamail import policy
    return policy.store().list_pending()


def test_il_vincolo_entra_nel_prompt(mondo, estensione):
    from gigamail import watcher as watcher_mod
    estensione(_Vieta("a", "PIPPO"))
    mondo["bozze"] = ["va bene"]
    watcher_mod.Watcher().tick()
    assert "NON SCRIVERE: PIPPO" in mondo["prompt"][0]
    assert len(_pending()) == 1


def test_bozza_respinta_si_riscrive_una_volta(mondo, estensione):
    from gigamail import watcher as watcher_mod
    estensione(_Vieta("a", "PIPPO"))
    mondo["bozze"] = ["c'e' PIPPO", "pulita"]
    watcher_mod.Watcher().tick()
    assert "togli PIPPO" in mondo["prompt"][1]
    assert [p["args"]["body"] for p in _pending()] == ["pulita"]


def test_la_riscritta_ripassa_da_tutti_i_controlli(mondo, estensione):
    """Corretta per un'estensione, sbagliata per l'altra: non passa."""
    from gigamail import watcher as watcher_mod
    estensione(_Vieta("a", "PIPPO"))
    estensione(_Vieta("b", "PLUTO"))
    mondo["bozze"] = ["PIPPO", "PLUTO"]
    watcher_mod.Watcher().tick()
    assert _pending() == []
    assert any("b non superato" in a for a in mondo["avvisi"])


def test_estensione_accesa_ma_assente_ferma_la_bozza(mondo, monkeypatch):
    from gigamail import watcher as watcher_mod
    monkeypatch.setenv("GIGAMAIL_EXTENSIONS", "inesistente")
    mondo["bozze"] = ["x", "x", "x"]
    watcher_mod.Watcher().tick()
    assert _pending() == []
    assert mondo["prompt"] == []   # l'agente non viene nemmeno chiamato


# ── installate nella cartella dati: sopravvivono agli aggiornamenti ──

def _finta_estensione(cartella, nome="prova_dati"):
    """Un'estensione installata come la lascerebbe pip --target."""
    pkg = cartella / f"gm_{nome}"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text(
        "from gigamail.core.extensions import Extension\n"
        "class E(Extension):\n"
        f"    name = '{nome}'\n"
        "    def draft_constraint(self, subject, body):\n"
        "        return 'DALLA CARTELLA DATI'\n", encoding="utf-8")
    info = cartella / f"gm_{nome}-0.1.dist-info"
    info.mkdir()
    (info / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: gm-{nome}\nVersion: 0.1\n", encoding="utf-8")
    (info / "entry_points.txt").write_text(
        f"[gigamail.extensions]\n{nome} = gm_{nome}:E\n", encoding="utf-8")


@pytest.fixture()
def radice(tmp_path, monkeypatch):
    import sys
    monkeypatch.setenv("GIGAMAIL_ROOT", str(tmp_path))
    prima = list(sys.path)
    yield tmp_path
    sys.path[:] = prima
    for m in [m for m in sys.modules if m.startswith("gm_")]:
        del sys.modules[m]


def test_la_cartella_estensioni_sta_nei_dati(radice):
    assert extensions.site_dir() == radice / "extensions"


def test_estensione_nella_cartella_dati_si_carica(radice, monkeypatch):
    import sys
    _finta_estensione(radice / "extensions")
    monkeypatch.setenv("GIGAMAIL_EXTENSIONS", "prova_dati")
    [ext] = extensions.active()
    assert ext.draft_constraint("", "") == "DALLA CARTELLA DATI"
    assert "(cartella dati)" in extensions.available()["prova_dati"]
    # in CODA: un file li' non puo' prendere il posto di un modulo del core
    assert sys.path[-1] == str(radice / "extensions")


def test_senza_cartella_sys_path_non_cambia(radice):
    import sys
    prima = list(sys.path)
    extensions.available()
    assert sys.path == prima


def test_nome_noto_dal_tag_della_versione_installata(monkeypatch):
    import importlib.metadata as md
    monkeypatch.setattr(md, "version", lambda nome: "0.4.0")
    spec = extensions.spec_for("real_estate")
    assert spec == ("gigamail-real-estate @ https://github.com/adecubed/gigamail/"
                    "archive/refs/tags/v0.4.0.zip#subdirectory=extras/real_estate")


def test_nome_noto_da_un_branch():
    assert "/refs/heads/main.zip#" in extensions.spec_for("real_estate", "main")
    assert "/refs/tags/v1.0.zip#" in extensions.spec_for("real_estate", "tags/v1.0")


def test_requisito_qualunque_passa_a_pip_cosi_com_e():
    assert extensions.spec_for("pkg @ file:///x.zip") == "pkg @ file:///x.zip"


def test_install_usa_pip_target_senza_dipendenze(radice, monkeypatch):
    import subprocess
    import sys
    visti = []

    class R:
        returncode, stdout, stderr = 0, "ok", ""
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: visti.append(cmd) or R())
    assert extensions.install("pkg") == (0, "ok")
    cmd = visti[0]
    assert cmd[:4] == [sys.executable, "-m", "pip", "install"]
    assert "--no-deps" in cmd
    assert cmd[cmd.index("--target") + 1] == str(radice / "extensions")
    assert cmd[-1] == "pkg"


def test_cli_install_chiede_la_verifica(radice, store, monkeypatch):
    from gigamail import cli
    chiamate = []
    monkeypatch.setattr(extensions, "install", lambda spec: chiamate.append(spec) or (0, ""))
    monkeypatch.setenv("GIGAMAIL_CONSENT_BACKEND", "deny")
    assert cli.main(["extensions", "install", "pkg"]) == 1
    assert chiamate == []
    monkeypatch.setenv("GIGAMAIL_CONSENT_BACKEND", "allow")
    monkeypatch.setenv("ADE_MAIL_DRYRUN", "1")
    assert cli.main(["extensions", "install", "pkg"]) == 0
    assert chiamate == ["pkg"]
