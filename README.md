# GigaMail — Mail for your AI agent

**MCP server that gives Claude (or any MCP-compatible agent) safe, controlled
access to your email** — multi-account (Microsoft Graph + IMAP), calendar,
local search index, sender memory, and an agent-aware permission model.

No built-in LLM: the intelligence is your agent's. No HTTP port: stdio
transport. Your data stays on your machine.

## Why

- **Hybrid search**: provider search (Graph/IMAP) + local SQLite index — fast
  and offline-friendly
- **Sender memory**: tone, topics and history per sender, so replies sound right
- **Observer**: patterns learned from how the user edited past drafts
- **Knowledge files**: attach your price lists, terms, product sheets to an
  account — the agent reads them to answer mail. Your agent doesn't need to
  know everything: the account carries its own knowledge
- **Agent-aware permissions**: reads are free; send/delete are two-phase
  (preview → one-time confirm token → execution) with a human in the loop;
  every write action lands in an append-only audit log
- **Credentials never touch the agent channel**: login and account management
  live in the CLI only — a prompt injection inside an email cannot add
  accounts or read secrets

## Quick start

```bash
pip install -e .                 # from a clone; PyPI package coming
ade-mail-agent login             # Microsoft device flow
# or
ade-mail-agent accounts add-imap # Aruba, Gmail, Libero, ...
```

Give the account its identity and knowledge (this is what makes replies yours):

```bash
ade-mail-agent identity set                       # who am I, what I do, tone
ade-mail-agent identity add-file C:\docs\pricelist.xlsx
ade-mail-agent identity add-file C:\docs\catalog\   # whole folder
```

Register in Claude Desktop / Claude Code (`mcpServers`):

```json
{
  "ade-mail": {
    "command": "ade-mail-agent-server"
  }
}
```

Then just ask your agent: *"reply to the last quote request using the price
list"* — it reads the mail, pulls the numbers from your file, drafts the
reply, and asks you before sending.

## Tools

23 typed tools. Reading: accounts, messages, folders, unread, hybrid search,
attachments (text extraction), sender history, knowledge files, calendar.
Safe writes (audited): mark read, move, create folder. Dangerous actions
(two-phase confirmation): send, reply, delete, spam, calendar events.
Full map and design decisions: [MAPPA_MCP.md](MAPPA_MCP.md).

## Security model

Email content is treated as **untrusted data** (prompt injection): dangerous
tools are never self-confirmable — the first call only returns a preview and
a one-time token; execution requires the user's explicit consent. The agent
can only read files explicitly registered by the user, never the rest of the
filesystem. Every write action is logged to `%APPDATA%/ADE/agent_audit.jsonl`.

## License

MIT

---

# GigaMail — La posta per il tuo agente AI

**Server MCP che dà a Claude (o a qualunque agente compatibile) accesso
sicuro e controllato alla tua posta** — multi-account (Microsoft Graph +
IMAP), calendario, indice di ricerca locale, memoria dei mittenti e un
modello di permessi pensato per gli agenti.

Nessun LLM interno: l'intelligenza è quella del tuo agente. Nessuna porta
HTTP: trasporto stdio. I dati restano sul tuo PC.

## Perché

- **Ricerca ibrida**: provider (Graph/IMAP) + indice SQLite locale — veloce e
  offline-friendly
- **Memoria dei mittenti**: tono, argomenti e storico per rispondere nel modo giusto
- **Observer**: pattern appresi dalle correzioni dell'utente alle bozze passate
- **File di conoscenza**: collega listini, condizioni, schede prodotto a un
  account — l'agente li legge per rispondere alle mail. Il tuo agente non
  deve sapere tutto: le informazioni che gli servono viaggiano con l'account
- **Permessi per agenti**: lettura libera; invio/cancellazione a due fasi
  (anteprima → token monouso → esecuzione) con conferma umana; audit log
  append-only di ogni azione di scrittura
- **Credenziali fuori dal canale agente**: login e gestione account solo via
  CLI — una prompt injection dentro una mail non può aggiungere account né
  leggere segreti

## Setup rapido

```bash
pip install -e .                 # da un clone; pacchetto PyPI in arrivo
ade-mail-agent login             # device flow Microsoft
# oppure
ade-mail-agent accounts add-imap # Aruba, Gmail, Libero, ...
```

Dai all'account la sua identità e la sua conoscenza (è ciò che rende le
risposte *tue*):

```bash
ade-mail-agent identity set                       # chi sono, cosa faccio, tono
ade-mail-agent identity add-file C:\docs\listino.xlsx
ade-mail-agent identity add-file C:\docs\catalogo\   # intera cartella
```

Registrazione in Claude Desktop / Claude Code (`mcpServers`):

```json
{
  "ade-mail": {
    "command": "ade-mail-agent-server"
  }
}
```

Poi chiedi al tuo agente: *"rispondi all'ultima richiesta di preventivo
usando il listino"* — legge la mail, prende i numeri dal tuo file, prepara la
risposta e ti chiede conferma prima di inviare.

## Tool

23 tool tipizzati. Lettura: account, messaggi, cartelle, non lette, ricerca
ibrida, allegati (estrazione testo), storico mittenti, file di conoscenza,
calendario. Scritture sicure (con audit): segna letto, sposta, crea cartella.
Azioni pericolose (conferma a due fasi): invio, risposta, cancellazione,
spam, eventi calendario. Mappa completa e decisioni di design:
[MAPPA_MCP.md](MAPPA_MCP.md).

## Modello di sicurezza

Il contenuto delle email è trattato come **dato non fidato** (prompt
injection): i tool pericolosi non sono mai auto-confermabili — la prima
chiamata restituisce solo un'anteprima e un token monouso; l'esecuzione
richiede il consenso esplicito dell'utente. L'agente può leggere solo i file
registrati esplicitamente dall'utente, mai il resto del filesystem. Ogni
azione di scrittura finisce in `%APPDATA%/ADE/agent_audit.jsonl`.

## Licenza

MIT
