"""Monta la demo per una scena e dice cosa fare in ripresa.

Un video per scena, non un video solo. Ogni scena porta in casella solo
cio' che le serve, cosi' l'inquadratura e' pulita e la ripresa si rifa'
identica quante volte serve.

    python demo_video/allestisci.py --scena 1   # allestisce e stampa il foglio
    python demo_video/allestisci.py             # tutte le mail insieme
    python demo_video/allestisci.py --riparti   # rimette la casella al via
    python demo_video/allestisci.py --stato     # cosa c'e' adesso

Non tocca la posta ne' la configurazione dell'utente: account, identity e
casella vivono in demo_video/.stato.
"""
import json
import os
import sys

import allestimento as demo  # dirotta la radice dati, va importato per primo

from ade_mail_agent import agent_bridge  # noqa: E402
from ade_mail_agent.core import accounts, demo_mailbox  # noqa: E402


# ── I fogli di ripresa ───────────────────────────────────────────────

FOGLI = {
    1: {
        "durata": "40-50 secondi",
        "vede": "La casella con due cartelle, Lead e Clienti. In Lead c'e' "
                "Giulia Rossi, in Clienti c'e' Marco Bianchi. Le due mail "
                "chiedono la stessa identica cosa.",
        "fa": [
            "Apri in Lead la mail di Giulia Rossi. Premi GENERA. Aspetta la bozza.",
            "Inquadra la bozza: breve, e propone i due orari per la visita.",
            "Chiudi. Apri in Clienti la mail di Marco Bianchi. Premi GENERA.",
            "Inquadra la seconda bozza accanto alla prima, se puoi in split.",
        ],
        "deve": "Le due risposte alla stessa domanda sono diverse nel tono e "
                "nel contenuto. Clienti e' formale, riepiloga i dati e scrive "
                "[DA COMPLETARE] sulla visita, perche' quella cartella gli "
                "orari non li ha.",
        "voce": "La cartella in cui sta la mail decide chi risponde. Non e' "
                "un modello diverso: e' la stessa richiesta, letta con "
                "l'identita' della cartella.",
        "non_dire": "Non dire che l'agente 'capisce' il contesto. Le due "
                    "identity sono scritte a mano dall'utente.",
    },
    3: {
        "durata": "30-40 secondi",
        "vede": "In Lead una sola mail: Giulia Rossi che chiede prezzo e box.",
        "fa": [
            "Apri la mail. Fai vedere che chiede il prezzo del trilocale A12.",
            "Premi GENERA.",
            "Inquadra la cifra nella bozza, poi il riquadro ALLEGATI SUGGERITI.",
            "Se serve una prova, apri il listino nella cartella dei documenti "
            "e mostra la stessa riga.",
        ],
        "deve": "La bozza dice 395.000 euro e box incluso, e propone "
                "scheda_A12.pdf in allegato.",
        "voce": "Il prezzo non se lo inventa il modello. Viene dal listino "
                "dell'utente, letto sul momento e messo davanti a chi scrive.",
        "non_dire": "Non dire che l'agente 'consulta il gestionale'. Legge "
                    "i file che l'utente gli ha indicato, niente di piu'.",
    },
    4: {
        "durata": "30-40 secondi",
        "vede": "In Lead la seconda mail di Giulia: chiede conferma del "
                "prezzo e se ci sono convenzioni bancarie per il mutuo.",
        "fa": [
            "Apri la mail. Leggi ad alta voce la domanda sulla banca.",
            "Premi GENERA.",
            "Fermo immagine sulla frase con il prezzo e sul marcatore.",
        ],
        "deve": "La bozza conferma il prezzo e scrive [DA COMPLETARE] sulla "
                "convenzione. Nei documenti la convenzione non esiste, e "
                "l'agente non se la inventa.",
        "voce": "Il dato vero e il limite, nella stessa frase. Dove non sa, "
                "lascia un buco visibile invece di riempirlo.",
        "non_dire": "Non dire che l'agente 'sa cosa non sa'. Sa cosa c'e' nei "
                    "documenti, e per il resto ha l'ordine di lasciare il "
                    "marcatore.",
    },
    7: {
        "durata": "40-50 secondi",
        "vede": "In Lead una mail dello studio legale. Dentro il testo ci "
                "sono istruzioni rivolte all'assistente.",
        "fa": [
            "Apri la mail e leggi ad alta voce il passaggio con le istruzioni.",
            "Premi GENERA.",
            "Fermo immagine sulla fascia rossa: motivi e passaggio citato.",
            "Inquadra il campo A: c'e' il mittente originale, non l'indirizzo "
            "che la mail chiedeva.",
        ],
        "deve": "Nessuna bozza. Campo del testo vuoto, nessun allegato "
                "proposto, la fascia elenca cosa e' stato riconosciuto.",
        "voce": "Il controllo gira prima della generazione e non interpella "
                "nessun modello. Il testo che analizza non puo' quindi "
                "convincerlo.",
        "non_dire": "Non dire che riconosce qualunque attacco. Riconosce le "
                    "formulazioni note, ed e' il primo strato. La difesa che "
                    "regge e' che il destinatario non si sposta.",
    },
}


def stampa_foglio(scena: int, lingua: str = "it") -> None:
    f = FOGLI[scena]
    cfg = demo.SCENE[scena]
    print(f"\n{'=' * 68}")
    print(f"VIDEO {scena} — {cfg['titolo'][lingua]}   ({f['durata']})")
    print("=" * 68)
    print(f"\nCosa si vede\n  {f['vede']}")
    print("\nCosa si fa")
    for i, passo in enumerate(f["fa"], 1):
        print(f"  {i}. {passo}")
    print(f"\nCosa deve succedere\n  {f['deve']}")
    print(f"\nVoce\n  \"{f['voce']}\"")
    print(f"\nDa non dire\n  {f['non_dire']}")


def scrivi_agent_json() -> str:
    """Fissa l'agente della demo: Claude Code senza server MCP montati.

    Con i tool della posta attaccati, l'agente smette di guardare la mail
    che ha gia' nel prompt e va a cercarne una per conto suo. Il file sta
    nella radice della demo, quindi vale solo qui."""
    percorso = agent_bridge._config_path()
    exe = ""
    for a in agent_bridge.status().get("agents", []):
        if a.get("id") == "claude" and a.get("found"):
            exe = a.get("exe") or ""
    if not exe:
        return ""
    with open(percorso, "w", encoding="utf-8") as f:
        json.dump({"command": [exe, "--strict-mcp-config", "--mcp-config",
                               '{"mcpServers":{}}', "-p", "{prompt}"],
                   "timeout": 180}, f, ensure_ascii=False, indent=2)
    return percorso


def mostra_stato(aid: int, lingua: str = "it") -> None:
    a = accounts.get_account_by_id(aid)
    quali = ["inbox"] + list(demo.NOMI_CARTELLA[lingua].values()) + \
            ["sentitems", "deleteditems"]
    for cartella in quali:
        msgs = demo_mailbox.get_messages(a, folder=cartella, top=50)
        if not msgs:
            continue
        print(f"\n[{cartella}]")
        for m in msgs:
            letta = " " if m["isRead"] else "*"
            mittente = m["from"]["emailAddress"]["address"]
            print(f"  {letta} {m['id']}  {mittente:<42} {m['subject']}")


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    argomenti = sys.argv[1:]

    scena = None
    lingua = "it"
    if "--scena" in argomenti:
        i = argomenti.index("--scena")
        if i + 1 < len(argomenti):
            scena = int(argomenti[i + 1])
        if scena not in demo.SCENE:
            print(f"Scene disponibili: {', '.join(str(s) for s in demo.SCENE)}")
            return 2
    if "--lingua" in argomenti:
        i = argomenti.index("--lingua")
        if i + 1 < len(argomenti):
            lingua = argomenti[i + 1]
        if lingua not in demo.LINGUE:
            print(f"Lingue: {', '.join(demo.LINGUE)}")
            return 2

    if "--riparti" in argomenti:
        aid = demo.prepara(scena, lingua=lingua)
        print("Casella rimessa al via"
              + (f" per la scena {scena}." if scena else "."))
        mostra_stato(aid, lingua)
        return 0

    if "--stato" in argomenti:
        aid = demo.account_demo(lingua)
        mostra_stato(aid, lingua)
        return 0

    aid = demo.prepara(scena, lingua=lingua)
    cfg = scrivi_agent_json()
    print(f"Radice dati della demo: {demo.STATO}")
    print(f"Documenti:              {demo.conoscenza(lingua)}")
    print(f"Account demo:           {aid}   (lingua {lingua})")
    print(f"Agente fissato in:      {cfg or '(nessun Claude Code trovato)'}")
    mostra_stato(aid, lingua)

    if scena:
        stampa_foglio(scena, lingua)
    else:
        print("\nUn video per scena. Per allestirne una:")
        for s, c in demo.SCENE.items():
            print(f"  python demo_video/allestisci.py --scena {s}"
                  f"   # {c['titolo'][lingua]}")

    print("\nPer girare, lancia la console con la radice della demo:\n")
    print(f'  $env:GIGAMAIL_ROOT = "{demo.STATO}"')
    print(f'  npm --prefix "{os.path.join(str(demo.RADICE), "console")}" start')
    print("\nFra un ciak e l'altro, stessa scena:"
          f"  python demo_video/allestisci.py --riparti"
          + (f" --scena {scena}" if scena else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
