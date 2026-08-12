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


def _resolve_account_id(account_id):
    import accounts as core_accounts
    if account_id:
        return account_id
    active = core_accounts.get_active_account()
    return active["id"] if active else None


def cmd_identity_show(args) -> int:
    import accounts as core_accounts
    aid = _resolve_account_id(args.account_id)
    if not aid:
        print("Nessun account. Usa 'login' o 'accounts add-imap'.")
        return 1
    ident = core_accounts.get_identity(aid)
    print(f"Identita account {aid}:")
    for k in ("who_am_i", "what_i_do", "tone", "key_info"):
        print(f"  {k}: {ident.get(k) or '(vuoto)'}")
    paths = ident.get("file_paths") or []
    print(f"  file di conoscenza ({len(paths)}):")
    for p in paths:
        print(f"    - {p}")
    return 0


def cmd_identity_set(args) -> int:
    import accounts as core_accounts
    aid = _resolve_account_id(args.account_id)
    if not aid:
        print("Nessun account.")
        return 1
    ident = core_accounts.get_identity(aid)
    print("Invio vuoto = mantieni il valore attuale.\n")
    fields = {}
    for key, label in (
        ("who_am_i", "Chi sono (es. 'Simone, titolare di ...')"),
        ("what_i_do", "Cosa faccio (attivita, servizi)"),
        ("tone", "Tono delle risposte (es. formale, diretto)"),
        ("key_info", "Info chiave (orari, condizioni, note ricorrenti)"),
    ):
        current = ident.get(key) or ""
        val = input(f"{label}\n  [{current[:60]}]: ").strip()
        fields[key] = val or current
    core_accounts.set_identity(aid, file_paths=ident.get("file_paths") or [], **fields)
    print("Identita salvata.")
    return 0


def cmd_identity_add_file(args) -> int:
    import os
    import accounts as core_accounts
    aid = _resolve_account_id(args.account_id)
    if not aid:
        print("Nessun account.")
        return 1
    path = os.path.abspath(args.path)
    if not os.path.exists(path):
        print(f"Percorso inesistente: {path}")
        return 1
    ident = core_accounts.get_identity(aid)
    paths = ident.get("file_paths") or []
    if path in paths:
        print("Gia registrato.")
        return 0
    paths.append(path)
    core_accounts.set_identity(
        aid, who_am_i=ident.get("who_am_i") or "",
        what_i_do=ident.get("what_i_do") or "", tone=ident.get("tone") or "",
        key_info=ident.get("key_info") or "", file_paths=paths,
    )
    kind = "cartella" if os.path.isdir(path) else "file"
    print(f"Registrato ({kind}): {path}")
    print("L'agente ora puo leggerlo con list_knowledge_files / read_knowledge_file.")
    return 0


def cmd_identity_remove_file(args) -> int:
    import os
    import accounts as core_accounts
    aid = _resolve_account_id(args.account_id)
    if not aid:
        print("Nessun account.")
        return 1
    ident = core_accounts.get_identity(aid)
    paths = ident.get("file_paths") or []
    target = os.path.abspath(args.path)
    remaining = [p for p in paths if p != target and p != args.path]
    if len(remaining) == len(paths):
        print("Percorso non trovato tra quelli registrati (usa 'identity show').")
        return 1
    core_accounts.set_identity(
        aid, who_am_i=ident.get("who_am_i") or "",
        what_i_do=ident.get("what_i_do") or "", tone=ident.get("tone") or "",
        key_info=ident.get("key_info") or "", file_paths=remaining,
    )
    print("Rimosso.")
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

    p_id = sub.add_parser("identity")
    id_sub = p_id.add_subparsers(dest="subcommand", required=True)
    p_show = id_sub.add_parser("show")
    p_show.add_argument("account_id", type=int, nargs="?", default=None)
    p_show.set_defaults(fn=cmd_identity_show)
    p_set = id_sub.add_parser("set")
    p_set.add_argument("account_id", type=int, nargs="?", default=None)
    p_set.set_defaults(fn=cmd_identity_set)
    p_addf = id_sub.add_parser("add-file")
    p_addf.add_argument("path")
    p_addf.add_argument("--account-id", type=int, default=None, dest="account_id")
    p_addf.set_defaults(fn=cmd_identity_add_file)
    p_rmf = id_sub.add_parser("remove-file")
    p_rmf.add_argument("path")
    p_rmf.add_argument("--account-id", type=int, default=None, dest="account_id")
    p_rmf.set_defaults(fn=cmd_identity_remove_file)

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
