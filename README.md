# ADE Mail Agent

**La posta per il tuo agente AI.** Server MCP che dà a Claude (o a qualunque
agente compatibile) accesso sicuro e controllato a email multi-account
(Microsoft Graph + IMAP) e calendario — con indice locale, memoria dei
mittenti e un modello di permessi pensato per gli agenti.

Nessun LLM interno: l'intelligenza è quella del tuo agente. Nessuna porta
HTTP: trasporto stdio. I dati restano sul tuo PC.

## Perché

- **Ricerca ibrida** su provider + indice SQLite locale (veloce, offline-friendly)
- **Memoria dei mittenti**: tono, argomenti, storico per rispondere nel modo giusto
- **Observer**: pattern appresi dalle correzioni dell'utente alle bozze passate
- **Permessi per agenti**: lettura libera; invio/cancellazione a due fasi con
  anteprima e conferma umana; audit log di ogni azione
- **Credenziali fuori dal canale agente**: login e account solo via CLI

## Setup rapido

```bash
pip install ade-mail-agent          # (quando pubblicato; per ora: pip install -e .)
ade-mail-agent login                # Microsoft device flow
# oppure
ade-mail-agent accounts add-imap    # Aruba, Gmail, Libero, ...
```

Configurazione in Claude Desktop / Claude Code (`mcpServers`):

```json
{
  "ade-mail": {
    "command": "ade-mail-agent-server"
  }
}
```

## Stato del progetto

Refactor in corso dalla codebase ADE Mail. Vedi [MAPPA_MCP.md](MAPPA_MCP.md)
per la mappa completa endpoint→tool e le decisioni di design.

### TODO prima del rilascio pubblico
- [ ] Convertire i moduli `core/` a import relativi (ora shim sys.path)
- [ ] Multi-account Microsoft reale: `auth.py` usa un token cache globale;
      va parametrizzato per `account_id` (oggi l'ultimo login vince)
- [ ] Integrare CalDAV nei tool calendario (ora solo Microsoft Graph)
- [ ] Masking (`ade_masker`) come filtro trasparente opzionale sugli output READ
- [ ] Cifratura chiave account con DPAPI (ora Fernet con chiave su file)
- [ ] Test: policy due fasi, router IMAP/Graph, estrazione allegati
- [ ] Repo git NUOVO (history pulita), licenza MIT, CI
- [ ] Publisher verification Azure per il client_id di produzione

## Sicurezza

Il contenuto delle email è trattato come **dato non fidato** (prompt
injection): i tool distruttivi non sono mai auto-confermabili — la prima
chiamata restituisce solo un'anteprima e un token monouso; serve il consenso
esplicito dell'utente per la seconda. Ogni azione di scrittura finisce in
`%APPDATA%/ADE/agent_audit.jsonl`.
