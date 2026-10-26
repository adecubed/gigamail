# GigaMail — mail for your AI agent
# Copyright (C) 2026 Adecubed
# Licensed under the GNU AGPL v3 or later. See LICENSE.
"""Onboarding check on a REAL account: login -> search -> a draft that does
not leave on its own -> human approval -> the mail arrives.

Works the same on Microsoft Graph and on IMAP. It sends ONE mail, to the
account's own address, and only after you approve it:

    gigamail check                   # active account
    gigamail check --account-id 2

While it waits, approve from another terminal (Windows Hello / Touch ID)
or from the console:

    gigamail approvals approve <request_id>

Each step prints PASS or FAIL; the exit code is 0 only if all pass. The
final block is meant to be pasted into INTEGRATIONS.md.
"""
import argparse
import platform
import sys
import time
import uuid
from datetime import datetime, timezone

from gigamail import __version__, policy
from gigamail import server as srv
from gigamail.core import accounts as core_accounts


def _passo(n, testo, ok, dettaglio=""):
    print(f"[{'PASS' if ok else 'FAIL'}] {n}. {testo}" + (f" — {dettaglio}" if dettaglio else ""))
    return ok


def _cerca(account_id, segno):
    r = srv.search_mail(query=segno, account_id=account_id, top=10)
    return [m for m in (r.get("provider") or []) + (r.get("archive") or [])
            if segno in str(m.get("subject") or "")]


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="gigamail check",
                                description=__doc__.split("\n\n")[0])
    p.add_argument("--account-id", type=int, default=None)
    p.add_argument("--timeout", type=int, default=600,
                   help="seconds to wait for your approval (default 600)")
    args = p.parse_args(argv)

    risultati = []
    acc = (core_accounts.get_account_by_id(args.account_id) if args.account_id
           else core_accounts.get_active_account())
    if not acc:
        _passo(1, "account", False, "no account: run `gigamail login` or "
                                    "`gigamail accounts add-imap` first")
        return 1
    aid, indirizzo, tipo = acc["id"], acc.get("email"), acc.get("type")
    risultati.append(_passo(1, "account", True, f"#{aid} {indirizzo} ({tipo})"))

    try:
        srv.list_unread(account_id=aid, top=1)
        risultati.append(_passo(2, "mailbox reachable", True))
    except Exception as e:
        _passo(2, "mailbox reachable", False, str(e)[:200])
        return 1

    try:
        r = srv.search_mail(query="a", account_id=aid, top=3)
        n = len(r.get("provider") or []) + len(r.get("archive") or [])
        risultati.append(_passo(3, "search", True, f"{n} results"))
    except Exception as e:
        risultati.append(_passo(3, "search", False, str(e)[:200]))

    segno = "gm-check-" + uuid.uuid4().hex[:8]
    oggetto = f"GigaMail onboarding check {segno}"
    corpo = ("This mail was sent by `gigamail check` after a human "
             "approved it. You can delete it.")
    prima = srv.send_mail(to=indirizzo, subject=oggetto, body=corpo, account_id=aid)
    rid = prima.get("request_id")
    risultati.append(_passo(4, "draft stops for approval",
                            prima.get("status") == "approval_required" and bool(rid),
                            f"request_id {rid}"))
    if not rid:
        return 1

    print(f"\n    Approve it now, from another terminal:\n"
          f"      gigamail approvals approve {rid}\n"
          f"    or from the console. Waiting up to {args.timeout}s...\n")
    fine = time.time() + args.timeout
    stato = None
    while time.time() < fine:
        riga = policy.store().get(rid) or {}
        stato = riga.get("status")
        if stato != policy.PENDING:
            break
        time.sleep(3)
    uscita_prima = _cerca(aid, segno)
    risultati.append(_passo(5, "nothing left before approval", not uscita_prima))
    if stato != policy.APPROVED:
        risultati.append(_passo(6, "human approval", False, f"status: {stato}"))
        return 1
    risultati.append(_passo(6, "human approval", True,
                            f"by {(policy.store().get(rid) or {}).get('decided_by')}"))

    dopo = srv.send_mail(to=indirizzo, subject=oggetto, body=corpo,
                         account_id=aid, request_id=rid)
    risultati.append(_passo(7, "send after approval", dopo.get("success") is True,
                            str(dopo.get("error") or "")[:200]))

    arrivata = []
    fine = time.time() + 120
    while time.time() < fine and not arrivata:
        time.sleep(5)
        arrivata = _cerca(aid, segno)
    risultati.append(_passo(8, "the mail arrives and is found", bool(arrivata)))

    ok = all(risultati)
    print("\n--- paste into INTEGRATIONS.md ---")
    print(f"{datetime.now(timezone.utc):%Y-%m-%d} · gigamail {__version__} · "
          f"{tipo} · {platform.system()} · onboarding check "
          f"{'PASSED' if ok else 'FAILED'} ({sum(risultati)}/{len(risultati)})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
