# GigaMail — mail for your AI agent
# Copyright (C) 2026 Adecubed
# Licensed under the GNU AGPL v3 or later. See LICENSE.
"""Quando l'agente non scrive la bozza, il fallimento deve emergere."""

import pytest

from ade_mail_agent import agent_bridge


def test_il_comando_si_ri_risolve_dopo_un_aggiornamento(tmp_path, monkeypatch):
    """Claude Code si aggiorna e cancella la cartella della versione
    precedente: un comando risolto poco prima punta a un percorso che non
    esiste piu'. Senza ri-risoluzione le bozze si fermano finche' qualcuno
    non se ne accorge — e nessuno se ne accorge."""
    vecchio = tmp_path / "2.1.247" / "claude.exe"
    nuovo = tmp_path / "2.1.258" / "claude.exe"
    nuovo.parent.mkdir(parents=True)
    nuovo.write_text("finto")

    monkeypatch.setattr(agent_bridge, "_find_claude", lambda: str(nuovo))
    monkeypatch.setattr(agent_bridge, "get_config", lambda: {
        "command": [str(vecchio), "-p", "{prompt}"], "timeout": 5})

    visti = {}

    def _finta_run(cmd, **kw):
        visti["cmd"] = cmd
        class R:
            returncode = 0
            stdout = b"bozza"
            stderr = b""
        return R()

    monkeypatch.setattr(agent_bridge.subprocess, "run", _finta_run)
    agent_bridge.run("prompt")
    assert visti["cmd"][0] == str(nuovo), "doveva ripiegare sulla versione nuova"


def test_se_non_c_e_proprio_lo_dice(tmp_path, monkeypatch):
    """La ri-risoluzione non deve trasformare un'assenza vera in un
    silenzio: se non c'e' nessun agente, l'errore resta."""
    monkeypatch.setattr(agent_bridge, "_find_claude", lambda: "claude")
    monkeypatch.setattr(agent_bridge, "get_config", lambda: {
        "command": ["claude", "-p", "{prompt}"], "timeout": 5})
    monkeypatch.setattr(agent_bridge.shutil, "which", lambda x: None)
    with pytest.raises(agent_bridge.AgentUnavailable) as e:
        agent_bridge.run("prompt")
    assert "non trovato" in str(e.value)


def test_i_tentativi_falliti_si_accumulano(tmp_path, monkeypatch):
    """Regressione: il conteggio vive in `reason`, ma record(...,
    'matched') a inizio giro fa INSERT OR REPLACE e lo azzera. Letto
    dopo, ripartiva da 1 ogni volta: la regola riprovava all'infinito e
    non raggiungeva mai la soglia che avvisa l'umano. Osservato dal vivo
    il 2026-09-03: 18 fallimenti di fila, tutti 'attempt 1'."""
    from ade_mail_agent.core import rules as rules_mod
    rs = rules_mod.store()
    RULE, MSG = "rule_test", "999"

    # com'e' fatto un giro: record() a inizio, set_status() alla fine
    for atteso in (1, 2, 3):
        prev = rs.get_handled(RULE, MSG) or {}
        import re
        m = re.match(r"^draft-attempt:(\d+)$", str(prev.get("reason") or ""))
        letti_prima = int(m.group(1)) if m else 0

        rs.record(RULE, 2, MSG, "x@y.it", "matched")     # azzera reason
        assert (rs.get_handled(RULE, MSG) or {}).get("reason") in (None, "")

        attempt = letti_prima + 1
        assert attempt == atteso, f"tentativo {attempt}, atteso {atteso}"
        rs.set_status(RULE, MSG, "retry", f"draft-attempt:{attempt}")


def test_un_prompt_lungo_passa_da_stdin(monkeypatch):
    """Il prompt porta identity, listino e il corpo della mail: come
    argomento sfonda il limite della riga di comando e il processo muore
    con "La riga di comando e' troppo lunga". Visto dal vivo il
    2026-09-04, e peggiorato dal fatto che npm installa `claude` come
    .CMD: quel wrapper passa da cmd.exe, che si ferma a 8191 caratteri."""
    visto = {}

    def _finta_run(cmd, **kw):
        visto["cmd"] = cmd
        visto["input"] = kw.get("input")
        class R:
            returncode = 0
            stdout = b"bozza"
            stderr = b""
        return R()

    monkeypatch.setattr(agent_bridge, "get_config", lambda: {
        "command": ["claude", "-p", "{prompt}", "--allowedTools", "x"],
        "timeout": 5})
    monkeypatch.setattr(agent_bridge.shutil, "which", lambda x: "claude")
    monkeypatch.setattr(agent_bridge.subprocess, "run", _finta_run)

    agent_bridge.run("x" * 30000)
    assert "{prompt}" not in " ".join(visto["cmd"])
    assert visto["input"] == b"x" * 30000      # il prompt e' su stdin
    assert not any(len(a) > 1000 for a in visto["cmd"])

    # un prompt corto resta argomento: nessun cambio di comportamento
    agent_bridge.run("ciao")
    assert "ciao" in visto["cmd"]
    assert visto["input"] is None


def test_un_agente_configurato_da_te_non_viene_sostituito(monkeypatch):
    """La ri-risoluzione vale solo per il comando che avremmo scelto noi.
    Se l'utente ha configurato un agente suo e quello manca, scambiarlo di
    nascosto con un altro sarebbe peggio dell'errore: farebbe scrivere le
    mail a un programma che non ha scelto."""
    monkeypatch.setattr(agent_bridge, "_find_claude",
                        lambda: r"C:\npm\claude.CMD")
    monkeypatch.setattr(agent_bridge, "get_config", lambda: {
        "command": ["mio-agente-inesistente", "{prompt}"], "timeout": 5})
    monkeypatch.setattr(agent_bridge.shutil, "which",
                        lambda x: None if "mio-agente" in x else x)
    with pytest.raises(agent_bridge.AgentUnavailable) as e:
        agent_bridge.run("ciao")
    assert "mio-agente-inesistente" in str(e.value)
