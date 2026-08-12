"""CLI di amministrazione di ADE Mail Agent.

Tutte le operazioni che toccano credenziali vivono QUI e mai nei tool MCP:
un agente (o una prompt injection dentro una mail) non può aggiungere account,
fare login o leggere segreti.

Comandi:
  ade-mail-agent login                    Device flow Microsoft (codice + link)
  ade-mail-agent logout
  ade-mail-agent accounts list
  ade-mail-agent accounts add-imap
  ade-mail-agent accounts remove <id>
  ade-mail-agent index [account_id]       Indicizza lo storico nell'indice locale
  ade-mail-agent purge <account_id>       Cancella i dati locali di un account
"""
import argparse
import getpass
import sys

import ade_mail_agent  # noqa: F401 — shim sys.path per core/


def cmd_login(_args) -> int:
    import requests as _requests
    import auth
    import accounts as core_accounts

    data = auth.get_login_url()
    print(f"\nApri: {data['verification_uri']}")
    print(f"Codice: {data['user_code']}")
    input("\nPremi INVIO dopo aver completato il login nel browser... ")
    if not auth.complete_login(data["flow"]):
        print("Login non riuscito.")
        return 1
    token = auth.get_token()
    me = _requests.get(
        "https://graph.microsoft.com/v1.0/me",
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    ).json()
    email_addr = me.get("mail") or me.get("userPrincipalName", "microsoft_user")
    name = me.get("displayName", "Account Microsoft")
    with open(auth.TOKEN_PATH, "r", encoding="utf-8") as f:
        token_cache = f.read()
    acc_id = core_accounts.add_microsoft_account(name, email_addr, token_cache)
    core_accounts.set_active_account(acc_id)
    print(f"Account Microsoft aggiunto: {email_addr} (id={acc_id})")
    return 0


def cmd_logout(_args) -> int:
    import auth
    auth.logout()
    print("Logout eseguito.")
    return 0


def cmd_accounts_list(_args) -> int:
    import accounts as core_accounts
    rows = core_accounts.get_accounts()
    if not rows:
        print("Nessun account configurato. Usa 'login' o 'accounts add-imap'.")
        return 0
    for a in rows:
        active = "*" if a.get("active") else " "
        print(f"{active} [{a['id']}] {a.get('email')} ({a.get('type', 'microsoft')})")
    return 0


def cmd_accounts_add_imap(_args) -> int:
    import accounts as core_accounts
    print("Configurazione account IMAP/SMTP")
    name = input("Nome visualizzato: ").strip()
    email_addr = input("Email: ").strip()
    password = getpass.getpass("Password (o password per le app): ")
    imap_host = input("Host IMAP (es. imaps.aruba.it): ").strip()
    imap_port = int(input("Porta IMAP [993]: ").strip() or "993")
    smtp_host = input("Host SMTP (es. smtps.aruba.it): ").strip()
    smtp_port = int(input("Porta SMTP [465]: ").strip() or "465")
    acc_id = core_accounts.add_imap_account(
        name, email_addr, password,
        imap_host=imap_host, imap_port=imap_port,
        smtp_host=smtp_host, smtp_port=smtp_port,
    )
    print(f"Account IMAP aggiunto: {email_addr} (id={acc_id})")
    return 0


def cmd_accounts_remove(args) -> int:
    import accounts as core_accounts
    a = core_accounts.get_account_by_id(args.account_id)
    if not a:
        print(f"Account {args.account_id} inesistente.")
        return 1
    confirm = input(f"Rimuovere {a.get('email')}? [y/N] ").strip().lower()
    if confirm != "y":
        print("Annullato.")
        return 0
    core_accounts.delete_account(args.account_id)
    print("Account rimosso. (Dati locali: usa 'purge' per cancellarli)")
    return 0


def cmd_index(args) -> int:
    import accounts as core_accounts
    import mail_memory
    import mail_router
    mail_memory.init_db()
    if args.account_id:
        result = mail_memory.run_indexer(args.account_id, mail_router)
    else:
        result = mail_memory.run_all_indexers(
            mail_router, lambda: [a["id"] for a in core_accounts.get_accounts()]
        )
    print(f"Indicizzazione: {result}")
    return 0


def cmd_purge(args) -> int:
    import mail_memory
    confirm = input(
        f"Cancellare TUTTI i dati locali dell'account {args.account_id}? [y/N] "
    ).strip().lower()
    if confirm != "y":
        print("Annullato.")
        return 0
    print(mail_memory.delete_account_data(args.account_id))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="ade-mail-agent")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("login").set_defaults(fn=cmd_login)
    sub.add_parser("logout").set_defaults(fn=cmd_logout)

    p_acc = sub.add_parser("accounts")
    acc_sub = p_acc.add_subparsers(dest="subcommand", required=True)
    acc_sub.add_parser("list").set_defaults(fn=cmd_accounts_list)
    acc_sub.add_parser("add-imap").set_defaults(fn=cmd_accounts_add_imap)
    p_rm = acc_sub.add_parser("remove")
    p_rm.add_argument("account_id", type=int)
    p_rm.set_defaults(fn=cmd_accounts_remove)

    p_idx = sub.add_parser("index")
    p_idx.add_argument("account_id", type=int, nargs="?", default=None)
    p_idx.set_defaults(fn=cmd_index)

    p_purge = sub.add_parser("purge")
    p_purge.add_argument("account_id", type=int)
    p_purge.set_defaults(fn=cmd_purge)

    args = parser.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
