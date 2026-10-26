"""Stop nella console: il processo dell'agente (e i suoi figli) termina
davvero, non solo l'attesa nella finestra."""

import sys
import threading
import time

import pytest

from gigamail import agent_bridge


def test_cancel_termina_un_giro_in_corso(monkeypatch):
    lento = [sys.executable, "-c", "import time; time.sleep(30); print('finito')"]
    errori = []

    def giro():
        try:
            agent_bridge._spawn(lento, None, 60, None, "run-cancel-1")
        except agent_bridge.AgentCancelled as e:
            errori.append(e)

    t = threading.Thread(target=giro)
    inizio = time.time()
    t.start()
    for _ in range(50):
        if "run-cancel-1" in agent_bridge._RUNNING:
            break
        time.sleep(0.1)
    assert agent_bridge.cancel("run-cancel-1") is True
    t.join(10)
    assert not t.is_alive()
    assert errori and time.time() - inizio < 15
    assert "run-cancel-1" not in agent_bridge._RUNNING


def test_stop_premuto_prima_che_il_processo_parta():
    assert agent_bridge.cancel("run-early-1") is False
    with pytest.raises(agent_bridge.AgentCancelled):
        agent_bridge._spawn([sys.executable, "-c", "import time; time.sleep(30)"], None, 60, None, "run-early-1")


def test_senza_run_id_il_percorso_resta_quello_di_prima(monkeypatch):
    rc, out, err = agent_bridge._spawn([sys.executable, "-c", "print('ok')"], None, 30, None, None)
    assert rc == 0 and out.strip() == b"ok"
