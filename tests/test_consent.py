"""Consenso umano sull'approvazione: cio' che un processo non puo' digitare.

Contesto (r/mcp, agosto 2026): un agente con la shell puo' lanciare
`gigamail approvals approve <id>`. Finche' quel comando bastava, il gate
era aggirabile dall'agente che doveva supervisionare. Ora approvare —
da CLI o da console — passa da un prompt dell'OS (Windows Hello / Touch
ID) che un processo puo' aprire ma non superare.

Questi test NON aprono prompt veri: conftest forza il backend 'deny';
qui si alternano 'deny' e 'allow' (quest'ultimo ammesso solo in dry-run).
Il comportamento reale dei backend e' documentato in SECURITY.md dal
test manuale (Windows 11, 2026-08-19: prompt a ogni chiamata, zero cache).
"""
import importlib
import types

import pytest
from fastapi.testclient import TestClient

from ade_mail_agent import consent, policy


@pytest.fixture(autouse=True)
def store_isolato(tmp_path):
    policy.set_store(policy.ApprovalStore(tmp_path / "approvals.db"))
    yield
    policy.set_store(None)


def _nuova_richiesta():
    return policy.store().create("send_mail", {"to": "a@b.it"}, {"to": "a@b.it"})


# ----------------------------------------------------------- modulo consent

def test_default_suite_nega(monkeypatch):
    monkeypatch.setenv("GIGAMAIL_CONSENT_BACKEND", "deny")
    assert consent.backend_name() == "test-override"
    assert consent.require_human("x") is False


def test_allow_vale_solo_in_dryrun(monkeypatch):
    monkeypatch.setenv("GIGAMAIL_CONSENT_BACKEND", "allow")
    monkeypatch.delenv("ADE_MAIL_DRYRUN", raising=False)
    # fuori dal dry-run 'allow' e' ignorato: torna il backend reale (o nessuno)
    assert consent._test_override() is None
    monkeypatch.setenv("ADE_MAIL_DRYRUN", "1")
    assert consent.require_human("x") is True


def test_senza_backend_solleva_non_approva(monkeypatch):
    """Nessun backend = ConsentUnavailable, mai True silenzioso."""
    monkeypatch.delenv("GIGAMAIL_CONSENT_BACKEND", raising=False)
    monkeypatch.setattr(consent, "_WIN", False)
    monkeypatch.setattr(consent, "_MAC", False)
    assert consent.available() is False
    with pytest.raises(consent.ConsentUnavailable):
        consent.require_human("x")


def test_backend_windows_nega_tutto_tranne_verified(monkeypatch):
    """Qualunque esito diverso da VERIFIED (annullato, occupato, tentativi
    esauriti...) e' un NO: fail-closed per costruzione."""
    monkeypatch.delenv("GIGAMAIL_CONSENT_BACKEND", raising=False)
    import asyncio
    for esito, atteso in ((0, True), (1, False), (2, False), (4, False), (5, False)):
        async def fake_request(_reason, _e=esito):
            return _e

        class R:
            VERIFIED = 0

        fake_mod = types.SimpleNamespace(
            UserConsentVerifier=types.SimpleNamespace(
                request_verification_async=fake_request),
            UserConsentVerificationResult=R,
        )
        monkeypatch.setitem(__import__("sys").modules,
                            "winrt.windows.security.credentials.ui", fake_mod)
        monkeypatch.setitem(__import__("sys").modules, "winrt", types.ModuleType("winrt"))
        monkeypatch.setitem(__import__("sys").modules, "winrt.windows", types.ModuleType("w"))
        monkeypatch.setitem(__import__("sys").modules, "winrt.windows.security", types.ModuleType("w"))
        monkeypatch.setitem(__import__("sys").modules, "winrt.windows.security.credentials", types.ModuleType("w"))
        assert consent._win_ask("x") is atteso, f"esito {esito}"


def test_macos_contesto_fresco_per_ogni_approvazione(monkeypatch):
    """r/mcp (ranbuman): la finestra di riuso di macOS appartiene
    all'ISTANZA di LAContext, non al processo — un contesto tenuto vivo
    puo' dare un successo silenzioso anche con reuseDuration al default.
    Quindi: un LAContext NUOVO per ogni approvazione, e reuseDuration=0
    su ciascuno. Questo test lo asserisce, cosi' nessun refactor potra'
    spostare il contesto a livello modulo senza che si accenda."""
    created = []

    class _FakeCtx:
        def __init__(self):
            self.reuse = None
            created.append(self)

        def setTouchIDAuthenticationAllowableReuseDuration_(self, v):
            self.reuse = v

        def evaluatePolicy_localizedReason_reply_(self, policy_, reason, reply):
            reply(True, None)

    fake_la = types.SimpleNamespace(
        LAContext=types.SimpleNamespace(
            alloc=lambda: types.SimpleNamespace(init=lambda: _FakeCtx())),
        LAPolicyDeviceOwnerAuthentication=1,
    )
    monkeypatch.setitem(__import__("sys").modules, "LocalAuthentication", fake_la)
    assert consent._mac_ask("prima") is True
    assert consent._mac_ask("seconda") is True
    assert len(created) == 2, "stesso LAContext riusato tra due approvazioni"
    assert all(c.reuse == 0 for c in created)


# ------------------------------------------------------------------- CLI

def _run_cli(argv):
    from ade_mail_agent import cli
    return cli.main(argv)


def test_cli_approve_non_ha_piu_yes():
    """--yes era la scorciatoia che un agente avrebbe usato. Sparita."""
    rid = _nuova_richiesta()
    with pytest.raises(SystemExit):
        _run_cli(["approvals", "approve", rid, "--yes"])
    assert policy.store().get(rid)["status"] == policy.PENDING


def test_cli_approve_negato_lascia_pending(monkeypatch):
    monkeypatch.setenv("GIGAMAIL_CONSENT_BACKEND", "deny")
    rid = _nuova_richiesta()
    assert _run_cli(["approvals", "approve", rid]) == 1
    assert policy.store().get(rid)["status"] == policy.PENDING


def test_cli_approve_senza_backend_rifiuta(monkeypatch):
    monkeypatch.delenv("GIGAMAIL_CONSENT_BACKEND", raising=False)
    monkeypatch.setattr(consent, "_WIN", False)
    monkeypatch.setattr(consent, "_MAC", False)
    rid = _nuova_richiesta()
    assert _run_cli(["approvals", "approve", rid]) == 2
    assert policy.store().get(rid)["status"] == policy.PENDING


def test_cli_approve_con_consenso_approva(monkeypatch):
    monkeypatch.setenv("GIGAMAIL_CONSENT_BACKEND", "allow")
    monkeypatch.setenv("ADE_MAIL_DRYRUN", "1")
    rid = _nuova_richiesta()
    assert _run_cli(["approvals", "approve", rid]) == 0
    assert policy.store().get(rid)["status"] == policy.APPROVED


def test_cli_reject_non_richiede_consenso(monkeypatch):
    """Rifiutare e' sempre sicuro: non serve il prompt (fail-closed)."""
    monkeypatch.setenv("GIGAMAIL_CONSENT_BACKEND", "deny")
    rid = _nuova_richiesta()
    assert _run_cli(["approvals", "reject", rid]) == 0
    assert policy.store().get(rid)["status"] == policy.REJECTED


# --------------------------------------------------------------- console

@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("ADE_CONSOLE_TOKEN", "tok")
    from ade_mail_agent import http_api
    importlib.reload(http_api)
    with TestClient(http_api.app) as c:
        yield c
    monkeypatch.delenv("ADE_CONSOLE_TOKEN")
    importlib.reload(http_api)


H = {"X-ADE-Token": "tok"}


def test_console_approve_col_solo_token_non_basta(client, monkeypatch):
    """Il token sta in un file: un processo puo' leggerlo e fare il POST.
    Senza consenso umano l'endpoint NON approva."""
    monkeypatch.setenv("GIGAMAIL_CONSENT_BACKEND", "deny")
    rid = _nuova_richiesta()
    r = client.post(f"/approvals/{rid}/approve", headers=H)
    assert r.status_code == 403
    assert policy.store().get(rid)["status"] == policy.PENDING


def test_console_approve_senza_backend_503(client, monkeypatch):
    monkeypatch.delenv("GIGAMAIL_CONSENT_BACKEND", raising=False)
    monkeypatch.setattr(consent, "_WIN", False)
    monkeypatch.setattr(consent, "_MAC", False)
    rid = _nuova_richiesta()
    r = client.post(f"/approvals/{rid}/approve", headers=H)
    assert r.status_code == 503
    assert policy.store().get(rid)["status"] == policy.PENDING


def test_console_approve_con_consenso(client, monkeypatch):
    monkeypatch.setenv("GIGAMAIL_CONSENT_BACKEND", "allow")
    monkeypatch.setenv("ADE_MAIL_DRYRUN", "1")
    rid = _nuova_richiesta()
    r = client.post(f"/approvals/{rid}/approve", headers=H)
    assert r.status_code == 200
    assert policy.store().get(rid)["status"] == policy.APPROVED


def test_console_reject_senza_consenso(client, monkeypatch):
    monkeypatch.setenv("GIGAMAIL_CONSENT_BACKEND", "deny")
    rid = _nuova_richiesta()
    r = client.post(f"/approvals/{rid}/reject", headers=H)
    assert r.status_code == 200
    assert policy.store().get(rid)["status"] == policy.REJECTED
