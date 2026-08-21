# GigaMail — mail for your AI agent
# Copyright (C) 2026 Adecubed
# Licensed under the GNU AGPL v3 or later. See LICENSE.
"""CLI di amministrazione di GigaMail.

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

from ade_mail_agent.core import accounts as _core_accounts  # noqa: F401


def cmd_login(_args) -> int:
    import requests as _requests
    from ade_mail_agent.core import auth
    from ade_mail_agent.core import accounts as core_accounts

    data = auth.get_login_url()
    print(f"\nApri: {data['verification_uri']}")
    print(f"Codice: {data['user_code']}")
    input("\nPremi INVIO dopo aver completato il login nel browser... ")
    result = auth.complete_login(data["flow"])
    if not result:
        print("Login non riuscito.")
        return 1
    me = _requests.get(
        "https://graph.microsoft.com/v1.0/me",
        headers={"Authorization": f"Bearer {result['access_token']}"},
        timeout=15,
    ).json()
    claims = result.get("id_token_claims", {})
    email_addr = (me.get("mail") or me.get("userPrincipalName")
                  or claims.get("preferred_username") or "microsoft_user")
    name = me.get("displayName") or claims.get("name") or "Account Microsoft"
    with open(auth.TOKEN_PATH, "r", encoding="utf-8") as f:
        token_cache = f.read()
    acc_id = core_accounts.add_microsoft_account(name, email_addr, token_cache)
    core_accounts.set_active_account(acc_id)
    print(f"Account Microsoft aggiunto: {email_addr} (id={acc_id})")
    return 0


def cmd_logout(_args) -> int:
    from ade_mail_agent.core import auth
    auth.logout()
    print("Logout eseguito.")
    return 0


def cmd_accounts_list(_args) -> int:
    from ade_mail_agent.core import accounts as core_accounts
    rows = core_accounts.get_accounts()
    if not rows:
        print("Nessun account configurato. Usa 'login' o 'accounts add-imap'.")
        return 0
    for a in rows:
        active = "*" if a.get("active") else " "
        print(f"{active} [{a['id']}] {a.get('email')} ({a.get('type', 'microsoft')})")
    return 0


def cmd_accounts_add_imap(_args) -> int:
    from ade_mail_agent.core import accounts as core_accounts
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
    from ade_mail_agent.core import accounts as core_accounts
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
    from ade_mail_agent.core import accounts as core_accounts
    if account_id:
        return account_id
    active = core_accounts.get_active_account()
    return active["id"] if active else None


def cmd_identity_show(args) -> int:
    from ade_mail_agent.core import accounts as core_accounts
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
    from ade_mail_agent.core import accounts as core_accounts
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
    from ade_mail_agent.core import accounts as core_accounts
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
    from ade_mail_agent.core import accounts as core_accounts
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


def _cli_who() -> str:
    import getpass
    try:
        return f"cli:{getpass.getuser()}"
    except Exception:
        return "cli"


def _fmt_preview(preview: dict) -> str:
    righe = []
    for k, v in (preview or {}).items():
        v = str(v)
        if len(v) > 300:
            v = v[:300] + "…"
        righe.append(f"    {k}: {v}")
    return "\n".join(righe) or "    (nessuna anteprima)"


def cmd_approvals_list(_args) -> int:
    from ade_mail_agent import policy
    pending = policy.store().list_pending()
    if not pending:
        print("Nessuna richiesta in attesa.")
        return 0
    print(f"{len(pending)} richiesta/e in attesa di approvazione:\n")
    for r in pending:
        import time as _t
        eta = int(r["expires_at"] - _t.time())
        print(f"  {r['request_id']}  [{r['tool']}]  scade tra {eta // 60}m{eta % 60:02d}s")
        print(_fmt_preview(r["preview"]))
        print()
    print("Approva con:  gigamail approvals approve <request_id>")
    print("Rifiuta con:  gigamail approvals reject <request_id>")
    return 0


def cmd_approvals_approve(args) -> int:
    """Approva una richiesta. L'approvazione richiede una verifica
    dell'utente fisico (Windows Hello / Touch ID): un processo — incluso
    l'agente, se ha una shell — puo' lanciare questo comando ma non puo'
    superare il prompt. Niente `--yes`: era la scorciatoia che un agente
    avrebbe usato. Se la macchina non ha un backend di consenso, il
    comando rifiuta e indica la console."""
    from ade_mail_agent import policy, consent
    rec = policy.store().get(args.request_id)
    if not rec:
        print(f"Richiesta '{args.request_id}' inesistente.")
        return 1
    print(f"Tool: {rec['tool']}\nAnteprima:\n{_fmt_preview(rec['preview'])}\n")
    reason = f"GigaMail: approvare {rec['tool']} ({args.request_id})?"
    try:
        ok = consent.require_human(reason)
    except consent.ConsentUnavailable as e:
        print(f"Impossibile approvare da CLI: {e}")
        return 2
    if not ok:
        print("Verifica non superata o annullata: la richiesta resta in attesa.")
        return 1
    if policy.store().approve(args.request_id, by=_cli_who()):
        print("Approvata. L'agente puo' ora completare l'azione.")
        return 0
    print("Non approvabile: gia' decisa o scaduta.")
    return 1


def cmd_approvals_reject(args) -> int:
    from ade_mail_agent import policy
    if policy.store().reject(args.request_id, by=_cli_who()):
        print("Rifiutata.")
        return 0
    print("Non rifiutabile: gia' decisa o scaduta.")
    return 1


def _hello_or_refuse(reason: str):
    """Verifica dell'utente fisico per le operazioni sulle regole. Ritorna
    il timestamp della verifica, o None (e spiega) se negata/impossibile.
    Fail-closed: senza backend di consenso le regole non si creano da CLI."""
    import time as _t
    from ade_mail_agent import consent
    try:
        ok = consent.require_human(reason)
    except consent.ConsentUnavailable as e:
        print(f"Impossibile: {e}")
        return None
    if not ok:
        print("Verifica non superata o annullata: nessuna modifica.")
        return None
    return _t.time()


def cmd_rules_add(args) -> int:
    """Crea una regola di risposta (semi-auto o auto). Con i flag
    (--senders/--folder, --style, --doc...) salta le domande; senza, chiede
    interattivamente. In entrambi i casi la conferma finale e' Windows
    Hello / Touch ID: una regola e' una pre-approvazione, e nasce solo
    dalle mani dell'utente fisico."""
    import os as _os
    from ade_mail_agent.core import accounts as core_accounts
    from ade_mail_agent.core import rules as rules_mod

    aid = _resolve_account_id(getattr(args, "account_id", None))
    if not aid:
        print("Nessun account. Usa 'login' o 'accounts add-imap'.")
        return 1
    acc = core_accounts.get_account_by_id(aid)
    if not acc:
        print(f"Account {aid} inesistente (vedi 'accounts list').")
        return 1
    print(f"Nuova regola di risposta per {acc.get('email')} (account {aid})\n")

    flag_senders = getattr(args, "senders", None)
    flag_folder = getattr(args, "folder", None)
    non_interactive = bool(flag_senders or flag_folder)

    if non_interactive:
        if flag_senders and flag_folder:
            print("--senders e --folder sono alternativi.")
            return 1
        if flag_senders:
            kind = "senders"
            values = [v.strip().lower() for v in flag_senders.split(",") if v.strip()]
        else:
            kind = "folder"
            values = [flag_folder.strip()]
        style = getattr(args, "style", None) or ""
        docs = []
        for p in getattr(args, "doc", None) or []:
            p = _os.path.abspath(p)
            if not _os.path.exists(p):
                print(f"Documento inesistente: {p}")
                return 1
            docs.append(p)
        mode = getattr(args, "mode", None) or "semi"
        if mode not in rules_mod.MODES:
            print(f"Modalita' '{mode}' non valida (semi|auto).")
            return 1
        first_contact = getattr(args, "first_contact", None) or "semi"
        daily_cap = getattr(args, "daily_cap", None) or rules_mod.DEFAULT_DAILY_CAP
        cooldown = getattr(args, "cooldown_hours", None)
        cooldown = rules_mod.DEFAULT_COOLDOWN_HOURS if cooldown is None else cooldown
        expiry = getattr(args, "expiry_days", None) or rules_mod.DEFAULT_EXPIRY_DAYS
    else:
        kind = ""
        while kind not in rules_mod.TRIGGER_KINDS:
            kind = input("Trigger — 'senders' (indirizzi) o 'folder' (cartella): ").strip().lower()
        if kind == "senders":
            raw = input("Indirizzi (separati da virgola): ").strip()
            values = [v.strip().lower() for v in raw.split(",") if v.strip()]
        else:
            values = [input("Nome cartella (es. INBOX.Leads): ").strip()]
            print("NB: trigger a cartella = mittente arbitrario. Le barriere "
                  "anti-spam e first_contact:semi restano davanti.")
        style = input("Stile/istruzioni per la risposta: ").strip()
        docs = []
        print("Documenti da cui la bozza puo' pescare (INVIO per terminare).")
        print("Solo questi: niente knowledge globale, niente ricerca in posta.")
        while True:
            p = input("  percorso documento: ").strip()
            if not p:
                break
            p = _os.path.abspath(p)
            if not _os.path.exists(p):
                print(f"  inesistente: {p}")
                continue
            docs.append(p)
        mode = ""
        while mode not in rules_mod.MODES:
            mode = input("Modalita' — 'semi' (ogni invio approvato con Hello) o "
                         "'auto' (invio senza approvazione, entro i limiti): ").strip().lower()
        first_contact = "semi"
        if mode == "auto":
            fc = input("Primo contatto da mittente nuovo: 'semi' (default, "
                       "consigliato) o 'auto': ").strip().lower()
            first_contact = fc if fc in rules_mod.MODES else "semi"

        def _num(prompt, default, cast=int):
            raw = input(f"{prompt} [{default}]: ").strip()
            try:
                return cast(raw) if raw else default
            except ValueError:
                return default

        daily_cap = _num("Tetto risposte/giorno", rules_mod.DEFAULT_DAILY_CAP)
        cooldown = _num("Cooldown per mittente (ore)", rules_mod.DEFAULT_COOLDOWN_HOURS, float)
        expiry = _num("Scadenza regola (giorni)", rules_mod.DEFAULT_EXPIRY_DAYS, float)

    if not values or not all(values):
        print("Trigger vuoto: annullato.")
        return 1
    if first_contact not in rules_mod.MODES:
        print(f"first_contact '{first_contact}' non valido (semi|auto).")
        return 1

    trig = ", ".join(values)
    print(f"\nRiepilogo: [{mode}] {kind}={trig}; docs={len(docs)}; "
          f"cap={daily_cap}/giorno; cooldown={cooldown}h; scade tra {expiry}g")
    hello_ts = _hello_or_refuse(
        f"GigaMail: creare la regola {mode.upper()} per {trig}?")
    if not hello_ts:
        return 1
    rule_id = rules_mod.store().create(
        account_id=aid, trigger_kind=kind, trigger_values=values,
        reply_style=style, doc_paths=docs, mode=mode,
        first_contact=first_contact, daily_cap=daily_cap,
        cooldown_hours=cooldown, expiry_days=expiry,
        created_by=_cli_who(), hello_verified_at=hello_ts)
    from ade_mail_agent.policy import audit
    audit("rule", {"rule_id": rule_id, "mode": mode, "trigger": values},
          "rule_created", detail=_cli_who())
    print(f"Regola creata: {rule_id}. Il watcher la usa da subito "
          "(avvialo con: gigamail watch).")
    return 0


def cmd_rules_list(_args) -> int:
    import time as _t
    from ade_mail_agent.core import rules as rules_mod
    rows = rules_mod.store().list_all()
    if not rows:
        print("Nessuna regola. Creane una con: gigamail rules add")
        return 0
    for r in rows:
        state = "PAUSA" if r["paused"] else ("SCADUTA" if r["expired"] else "attiva")
        days_left = int((r["expires_at"] - _t.time()) / 86400)
        trig = ", ".join(r["trigger_values"])
        print(f"  {r['rule_id']}  [{r['mode']}] {r['trigger_kind']}={trig}  "
              f"({state}, scade tra {max(days_left, 0)}g, "
              f"cap {r['daily_cap']}/g)")
        if r["paused"] and r["pause_reason"]:
            print(f"    motivo pausa: {r['pause_reason']}")
    return 0


def cmd_rules_pause(args) -> int:
    from ade_mail_agent.core import rules as rules_mod
    if rules_mod.store().pause(args.rule_id, "pausa manuale"):
        print("Regola in pausa. Riattiva con: gigamail rules resume "
              f"{args.rule_id} (richiede Hello)")
        return 0
    print("Regola inesistente.")
    return 1


def cmd_rules_resume(args) -> int:
    from ade_mail_agent.core import rules as rules_mod
    rule = rules_mod.store().get(args.rule_id)
    if not rule:
        print("Regola inesistente.")
        return 1
    hello_ts = _hello_or_refuse(
        f"GigaMail: riattivare la regola {args.rule_id}?")
    if not hello_ts:
        return 1
    rules_mod.store().resume(args.rule_id, hello_ts)
    from ade_mail_agent.policy import audit
    audit("rule", {"rule_id": args.rule_id}, "rule_resumed", detail=_cli_who())
    print("Regola riattivata.")
    return 0


def cmd_rules_remove(args) -> int:
    from ade_mail_agent.core import rules as rules_mod
    if rules_mod.store().delete(args.rule_id):
        from ade_mail_agent.policy import audit
        audit("rule", {"rule_id": args.rule_id}, "rule_deleted", detail=_cli_who())
        print("Regola eliminata.")
        return 0
    print("Regola inesistente.")
    return 1


def cmd_watch(args) -> int:
    from ade_mail_agent.watcher import Watcher
    try:
        Watcher(interval=args.interval, verbose=args.verbose).run(once=args.once)
    except KeyboardInterrupt:
        print("\nWatcher fermato.")
    return 0


def cmd_index(args) -> int:
    from ade_mail_agent.core import accounts as core_accounts
    from ade_mail_agent.core import mail_memory
    from ade_mail_agent.core import mail_router
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
    from ade_mail_agent.core import mail_memory
    confirm = input(
        f"Cancellare TUTTI i dati locali dell'account {args.account_id}? [y/N] "
    ).strip().lower()
    if confirm != "y":
        print("Annullato.")
        return 0
    print(mail_memory.delete_account_data(args.account_id))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="gigamail")
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

    p_appr = sub.add_parser("approvals", help="approva le azioni richieste dall'agente")
    appr_sub = p_appr.add_subparsers(dest="subcommand", required=True)
    appr_sub.add_parser("list").set_defaults(fn=cmd_approvals_list)
    p_ok = appr_sub.add_parser(
        "approve",
        help="approva una richiesta (richiede Windows Hello / Touch ID)")
    p_ok.add_argument("request_id")
    p_ok.set_defaults(fn=cmd_approvals_approve)
    p_no = appr_sub.add_parser("reject")
    p_no.add_argument("request_id")
    p_no.set_defaults(fn=cmd_approvals_reject)

    p_rules = sub.add_parser(
        "rules", help="regole di risposta semi-auto/auto (creazione dietro Hello)")
    rules_sub = p_rules.add_subparsers(dest="subcommand", required=True)
    p_radd = rules_sub.add_parser(
        "add", help="crea una regola (richiede Windows Hello / Touch ID)")
    p_radd.add_argument("--senders", help="indirizzi trigger, separati da virgola")
    p_radd.add_argument("--folder", help="cartella trigger (alternativa a --senders)")
    p_radd.add_argument("--style", help="stile/istruzioni per la risposta")
    p_radd.add_argument("--doc", action="append",
                        help="documento sorgente (ripetibile)")
    p_radd.add_argument("--mode", choices=["semi", "auto"], default=None)
    p_radd.add_argument("--first-contact", choices=["semi", "auto"],
                        default=None, dest="first_contact")
    p_radd.add_argument("--daily-cap", type=int, default=None, dest="daily_cap")
    p_radd.add_argument("--cooldown-hours", type=float, default=None,
                        dest="cooldown_hours")
    p_radd.add_argument("--expiry-days", type=float, default=None,
                        dest="expiry_days")
    p_radd.add_argument("--account-id", type=int, default=None,
                        dest="account_id")
    p_radd.set_defaults(fn=cmd_rules_add)
    rules_sub.add_parser("list").set_defaults(fn=cmd_rules_list)
    p_pause = rules_sub.add_parser("pause")
    p_pause.add_argument("rule_id")
    p_pause.set_defaults(fn=cmd_rules_pause)
    p_resume = rules_sub.add_parser(
        "resume", help="riattiva una regola (richiede Windows Hello / Touch ID)")
    p_resume.add_argument("rule_id")
    p_resume.set_defaults(fn=cmd_rules_resume)
    p_rrm = rules_sub.add_parser("remove")
    p_rrm.add_argument("rule_id")
    p_rrm.set_defaults(fn=cmd_rules_remove)

    p_watch = sub.add_parser(
        "watch", help="processo che applica le regole alla posta in arrivo")
    p_watch.add_argument("--once", action="store_true",
                         help="un solo giro, poi esce")
    p_watch.add_argument("--interval", type=int, default=60,
                         help="secondi tra un giro e l'altro (default 60)")
    p_watch.add_argument("--verbose", action="store_true")
    p_watch.set_defaults(fn=cmd_watch)

    p_idx = sub.add_parser("index")
    p_idx.add_argument("account_id", type=int, nargs="?", default=None)
    p_idx.set_defaults(fn=cmd_index)

    p_purge = sub.add_parser("purge")
    p_purge.add_argument("account_id", type=int)
    p_purge.set_defaults(fn=cmd_purge)

    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
