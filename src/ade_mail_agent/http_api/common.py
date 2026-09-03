"""Helper condivisi dai router: account attivo e chi sta agendo."""
from typing import Optional

from ade_mail_agent.core import accounts as core_accounts


def _active_id() -> Optional[int]:
    a = core_accounts.get_active_account()
    return a["id"] if a else None

def _who() -> str:
    import getpass
    try:
        return f"console:{getpass.getuser()}"
    except Exception:
        return "console"
