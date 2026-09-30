"""Il package si chiama gigamail; ade_mail_agent resta come alias.

Fuori dal repository il nome vecchio c'e' ancora: configurazioni MCP con
`python -m ade_mail_agent.server`, il protocollo gigamail:// registrato in
HKLM come `-m ade_mail_agent.cli`, script che importavano i moduli."""
import subprocess
import sys


def test_stesso_oggetto_modulo_non_una_copia():
    """Con due copie ci sarebbero due store e due cache."""
    import ade_mail_agent.core.rules as vecchio

    import gigamail.core.rules as nuovo
    assert vecchio is nuovo
    import gigamail.policy
    from ade_mail_agent import policy
    assert policy is gigamail.policy


def test_versione_dal_nome_vecchio():
    import ade_mail_agent
    import gigamail
    assert ade_mail_agent.__version__ == gigamail.__version__


def test_python_m_col_nome_vecchio():
    r = subprocess.run([sys.executable, "-m", "ade_mail_agent.cli", "--help"],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert "extensions" in r.stdout


def test_package_con_main_col_nome_vecchio():
    import runpy
    nome, _spec, codice = runpy._get_module_details("ade_mail_agent.http_api")
    assert nome == "ade_mail_agent.http_api.__main__"
    assert codice.co_filename.replace("\\", "/").endswith("gigamail/http_api/__main__.py")


def test_protocollo_registrato_col_nome_vecchio_vale_ancora(tmp_path):
    """Senza, le toast perdevano i bottoni fino a un nuovo desktop-setup."""
    from gigamail.core import desktop_notify as d
    exe = tmp_path / "python.exe"
    exe.write_bytes(b"")
    assert d.registered_command_ok(f'"{exe}" -m ade_mail_agent.cli open-url "%1"')
    assert d.registered_command_ok(f'"{exe}" -m gigamail.cli open-url "%1"')
