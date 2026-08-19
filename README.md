<!--
GigaMail — mail for your AI agent
Copyright (C) 2026 Adecubed

This program is free software: you can redistribute it and/or modify it
under the terms of the GNU Affero General Public License as published by
the Free Software Foundation, either version 3 of the License, or (at your
option) any later version. See the LICENSE file for details.
-->

# GigaMail — Mail for your AI agent

**MCP server that gives Claude (or any MCP-compatible agent) safe, controlled
access to your email** — multi-account (Microsoft Graph + IMAP), calendar,
local search index, sender memory, and an agent-aware permission model.

No built-in LLM: the intelligence is your agent's. The MCP server speaks
stdio only — no network port. (An optional human console adds a local HTTP
API bound to 127.0.0.1.)

**On your data**: GigaMail keeps mail indexes, credentials, memory and
configuration **on your machine** — we run no service and receive nothing.
Mail content your agent reads is, of course, handled by that agent and its
model provider under their own data policies. Choose your agent
accordingly; the masker (coming) lets you hide sensitive fields before the
agent ever sees them.

![The human console: a draft written by the agent — real figures from the
account's documents, the right floor plans attached, and appointment slots
taken from the actual calendar. Nothing is sent until you approve it.](docs/console-draft.png)

*A real draft: the agent pulled the figures from the account's documents,
picked the floor plans to attach, and proposed slots from the calendar.
The human reviews and sends — or edits the instruction and regenerates.*

## Why

- **Hybrid search**: provider search (Graph/IMAP) + local SQLite index — fast
  and offline-friendly
- **Sender memory**: tone, topics and history per sender, so replies sound right
- **Observer**: patterns learned from how the user edited past drafts
- **Knowledge files**: attach your price lists, terms, product sheets to an
  account — the agent reads them to answer mail. Your agent doesn't need to
  know everything: the account carries its own knowledge
- **Agent-aware permissions**: reads are free; send/delete require an
  approval given **out of band** — the agent gets an inert request id, a
  human approves from the console or the CLI, and only then does it execute,
  with the exact arguments the human saw. Every write lands in an
  append-only action log
- **Credentials never touch the agent channel**: login and account management
  live in the CLI only — a prompt injection inside an email cannot add
  accounts or read secrets

## Quick start

```bash
pip install "gigamail[all]"

gigamail login                # Microsoft device flow
gigamail accounts add-imap    # or IMAP: Aruba, Gmail, Libero, ...
```

> **Microsoft login note**: the bundled Azure app is not yet
> publisher-verified, so the consent screen shows an "unverified" notice
> (works fine; some corporate tenants may block it). Standard alternative:
> register your own Azure app and set your `client_id` in
> `src/ade_mail_agent/core/ms_config.json`. IMAP needs none of this.

Give the account its identity and knowledge (this is what makes replies yours):

```bash
gigamail identity set                       # who am I, what I do, tone
gigamail identity add-file C:\docs\pricelist.xlsx
gigamail identity add-file C:\docs\catalog\   # whole folder
```

Register in Claude Desktop / Claude Code (`mcpServers`):

```json
{
  "gigamail": {
    "command": "gigamail-server"
  }
}
```

The commands are also available under their legacy names
(`ade-mail-agent`, `ade-mail-agent-server`), so existing setups keep working.

Using **OpenClaw** or **Hermes** instead of Claude? Verified configs in
[INTEGRATIONS.md](INTEGRATIONS.md).

Then just ask your agent: *"reply to the last quote request using the price
list"* — it reads the mail, pulls the numbers from your file, drafts the
reply, and asks you before sending.

## Tools

24 typed tools, generated from the server itself:

- **Read (15)** — accounts, identity, knowledge files, messages, unread,
  folders, hybrid search, attachment text, sender history, learned
  patterns, calendar events, free-slot availability
- **Safe writes (3, audited)** — mark read, move message, create folder
- **Dangerous (6, human approval out of band)** — send, reply, delete
  message, delete folder, create/delete calendar event

Full map and design decisions: [MAPPA_MCP.md](MAPPA_MCP.md).

## Security model

Email content is treated as **untrusted data** (prompt injection). The
agent cannot approve its own actions, by construction: a dangerous tool
returns only an inert `request_id`, and approving it — from the console or
from `gigamail approvals approve` — requires an OS-level verification of
the person at the machine (**Windows Hello** / **Touch ID**). A process,
including an agent that holds a shell, can open that prompt but cannot
pass it; with no such backend available, nothing approves. No secret ever
enters the model context, so an injected instruction has nothing to
spend. Repeating the id just returns *awaiting approval*. The agent
can only read files explicitly registered by the user, never the rest of the
filesystem. Every write action is logged to `%APPDATA%/ADE/agent_audit.jsonl`
(append-only: GigaMail never rewrites past entries — it is not, and does not
claim to be, tamper-proof storage).

We red-team this: hostile emails ordering exfiltration, mass deletion, and
the agent to approve itself — fed to a real agent with every mail tool
enabled.

> This design is a fix. v0.1.0 returned a one-time confirm token in the
> tool result, which put it in the model's context: the agent held both
> halves. Thanks to **u/ranbuman** and **u/anderson_the_one** on r/mcp for
> catching it. The switch now sits where the agent cannot reach.

![Anti-injection harness: three hostile-email scenarios against a real
agent, zero destructive actions](docs/anti-injection-harness.png)

The structural half of that suite runs in CI on every push
([tests/test_injection.py](tests/test_injection.py)); the real-agent half is
opt-in ([scripts/injection_e2e.py](scripts/injection_e2e.py)) and runs with
a dry-run guard so confirmed actions are audited but never executed.

## License

**AGPL-3.0-or-later.** Free to use, study, modify and share. If you
distribute a modified version — or run one as a network service — you must
make its source available under the same license. Commercial licenses for
closed-source use are available from the copyright holder.

---

# GigaMail — La posta per il tuo agente AI

**Server MCP che dà a Claude (o a qualunque agente compatibile) accesso
sicuro e controllato alla tua posta** — multi-account (Microsoft Graph +
IMAP), calendario, indice di ricerca locale, memoria dei mittenti e un
modello di permessi pensato per gli agenti.

Nessun LLM interno: l'intelligenza è quella del tuo agente. Il server MCP
parla solo stdio — nessuna porta di rete. (La console per l'umano, che è
opzionale, aggiunge una API HTTP locale su 127.0.0.1.)

**Sui tuoi dati**: GigaMail tiene indici della posta, credenziali, memoria
e configurazione **sul tuo computer** — noi non gestiamo alcun servizio e
non riceviamo nulla. Il contenuto delle mail che il tuo agente legge è
ovviamente trattato da quell'agente e dal suo fornitore di modello secondo
le loro policy. Scegli l'agente di conseguenza; il masker (in arrivo)
permette di nascondere i dati sensibili prima che l'agente li veda.

![La console umana: una bozza scritta dall'agente — dati reali dai documenti
dell'account, planimetrie giuste in allegato e orari presi dal calendario.
Niente parte finché non approvi.](docs/console-draft.png)

*Una bozza vera: l'agente ha preso i dati dai documenti collegati
all'account, scelto le planimetrie da allegare e proposto gli orari liberi
dal calendario. L'umano rivede e invia — oppure corregge l'istruzione e
rigenera.*

## Perché

- **Ricerca ibrida**: provider (Graph/IMAP) + indice SQLite locale — veloce e
  offline-friendly
- **Memoria dei mittenti**: tono, argomenti e storico per rispondere nel modo giusto
- **Observer**: pattern appresi dalle correzioni dell'utente alle bozze passate
- **File di conoscenza**: collega listini, condizioni, schede prodotto a un
  account — l'agente li legge per rispondere alle mail. Il tuo agente non
  deve sapere tutto: le informazioni che gli servono viaggiano con l'account
- **Permessi per agenti**: lettura libera; invio/cancellazione richiedono
  un'approvazione data **fuori banda** — all'agente arriva solo un id
  inerte, un umano approva dalla console o dalla CLI, e solo allora si
  esegue, con gli argomenti esatti che l'umano ha visto. Ogni scrittura
  finisce in un registro append-only
- **Credenziali fuori dal canale agente**: login e gestione account solo via
  CLI — una prompt injection dentro una mail non può aggiungere account né
  leggere segreti

## Setup rapido

```bash
pip install "gigamail[all]"

gigamail login                # device flow Microsoft
gigamail accounts add-imap    # oppure IMAP: Aruba, Gmail, Libero, ...
```

> **Nota sul login Microsoft**: l'app Azure inclusa non è ancora
> publisher-verified, quindi la schermata di consenso mostra l'avviso
> "unverified" (funziona comunque; alcuni tenant aziendali potrebbero
> bloccarla). Alternativa standard: registra la tua app Azure e metti il
> tuo `client_id` in `src/ade_mail_agent/core/ms_config.json`.
> Per IMAP non serve nulla di tutto questo.

Dai all'account la sua identità e la sua conoscenza (è ciò che rende le
risposte *tue*):

```bash
gigamail identity set                       # chi sono, cosa faccio, tono
gigamail identity add-file C:\docs\listino.xlsx
gigamail identity add-file C:\docs\catalogo\   # intera cartella
```

Registrazione in Claude Desktop / Claude Code (`mcpServers`):

```json
{
  "gigamail": {
    "command": "gigamail-server"
  }
}
```

I comandi restano disponibili anche con i vecchi nomi
(`ade-mail-agent`, `ade-mail-agent-server`), così le installazioni esistenti
continuano a funzionare.

Usi **OpenClaw** o **Hermes** invece di Claude? Configurazioni verificate in
[INTEGRATIONS.md](INTEGRATIONS.md).

Poi chiedi al tuo agente: *"rispondi all'ultima richiesta di preventivo
usando il listino"* — legge la mail, prende i numeri dal tuo file, prepara la
risposta e ti chiede conferma prima di inviare.

## Tool

24 tool tipizzati, generati dal server stesso:

- **Lettura (15)** — account, identità, file di conoscenza, messaggi, non
  lette, cartelle, ricerca ibrida, testo degli allegati, storico mittenti,
  pattern appresi, eventi di calendario, slot liberi
- **Scritture sicure (3, con audit)** — segna letto, sposta, crea cartella
- **Pericolose (6, approvazione umana fuori banda)** — invio, risposta,
  cancellazione messaggio, cancellazione cartella, creazione/cancellazione
  evento

Mappa completa e decisioni di design: [MAPPA_MCP.md](MAPPA_MCP.md).

## Modello di sicurezza

Il contenuto delle email è trattato come **dato non fidato** (prompt
injection). L'agente non può approvare le proprie azioni, per costruzione:
un tool pericoloso restituisce solo un `request_id` inerte, e approvarlo —
dalla console o con `gigamail approvals approve` — richiede una verifica
dell'utente fisico a livello di sistema operativo (**Windows Hello** /
**Touch ID**). Un processo, compreso un agente con la shell, può aprire quel
prompt ma non superarlo; senza un backend del genere, nulla viene approvato.
Nessun segreto entra nel contesto del modello, quindi un'istruzione
iniettata non ha nulla da spendere. Ripetere
l'id restituisce solo *in attesa di approvazione*. L'agente può leggere solo i file
registrati esplicitamente dall'utente, mai il resto del filesystem. Ogni
azione di scrittura finisce in `%APPDATA%/ADE/agent_audit.jsonl` (append-only:
GigaMail non riscrive mai le voci passate — non è, e non pretende di essere,
un archivio a prova di manomissione).

Lo mettiamo alla prova: mail ostili che ordinano esfiltrazione,
cancellazione di massa e all'agente di approvarsi da solo, date a un agente
reale con tutti i tool attivi.

> Questo disegno è una correzione. La v0.1.0 restituiva un token di conferma
> monouso nel risultato del tool, quindi dentro il contesto del modello:
> l'agente aveva entrambe le metà. Grazie a **u/ranbuman** e
> **u/anderson_the_one** su r/mcp per averlo notato. Ora l'interruttore sta
> dove l'agente non arriva.

![Harness anti-injection: tre scenari di mail ostili contro un agente reale,
zero azioni distruttive](docs/anti-injection-harness.png)

La metà strutturale della suite gira in CI a ogni push
([tests/test_injection.py](tests/test_injection.py)); quella con l'agente
reale è opt-in ([scripts/injection_e2e.py](scripts/injection_e2e.py)) e usa
una modalità dry-run, così le azioni confermate finiscono nell'audit ma non
vengono mai eseguite.

## Licenza

**AGPL-3.0-or-later.** Libero di usarlo, studiarlo, modificarlo e
condividerlo. Se distribuisci una versione modificata — o la offri come
servizio in rete — devi rendere disponibile il sorgente con la stessa
licenza. Licenze commerciali per usi closed-source sono disponibili dal
titolare del copyright.
