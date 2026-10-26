<a id="english"></a>

# GigaMail — Map: MCP surface and risk classes

**English** · [Italiano](#italiano)

How GigaMail's capabilities are exposed to an agent, and under which policy.

**Two surfaces, one core:**

| Surface | Who uses it | Transport |
|---|---|---|
| MCP server | the agent | **stdio**, no network port |
| Console (optional) | the human | local HTTP API on `127.0.0.1`, session token |

No built-in LLM in either: the reasoning always belongs to the user's
agent (from the console it goes through `agent_bridge`).

Every tool has a **risk class** that sets its policy:

| Class | Policy | Examples |
|---|---|---|
| `READ` | free | reading, search, listings |
| `WRITE_SAFE` | free + audit log | mark as read, create a folder |
| `DANGEROUS` | two-phase confirmation + audit log | send, reply, delete, calendar events |
| `ADMIN` | **CLI only, never exposed to the agent** | login, credentials, account management |

Two-phase confirmation works like this: the first call (without `request_id`) does
NOT execute; it returns a full preview plus an **inert** `request_id` (valid for
15 minutes, `GIGAMAIL_APPROVAL_TTL`). Approval happens **out of band** — console,
CLI or Telegram, behind Windows Hello / Touch ID — never through the agent: the agent
shows the preview, waits for the human to approve, then calls the same tool again with
the `request_id`. What runs is the approved payload, not the one the agent passes back;
an approved request that has not run yet can be revoked.

---

## 1. Accounts

| Current endpoint | MCP tool | Class | Notes |
|---|---|---|---|
| `GET /accounts` | `list_accounts` | READ | No sensitive data (no password/token in the payload) |
| `GET /accounts/active` | — (included in `list_accounts`) | — | `active` flag per account |
| `POST /accounts/active/{id}` | — | — | Not needed: every tool takes an optional `account_id` |
| `DELETE /accounts/{id}` | — | ADMIN | CLI only: `gigamail accounts remove` |
| `GET /accounts/{id}/identity` | `get_identity` | READ | "Who I am / what I do / tone" context the agent needs to write drafts |
| `POST /accounts/{id}/identity` | — | ADMIN | CLI only: `gigamail identity set` (the agent reads the identity, never changes it: a hostile mail cannot poison it) |
| `GET /accounts/{id}/identity/files` | `list_knowledge_files` | READ | Knowledge files registered by the user (price lists, terms, data sheets) |
| reading an identity file | `read_knowledge_file` | READ | Extracts the text of a registered file. Allow-list = ONLY the paths registered via CLI (`identity add-file`), never the rest of the filesystem |
| search inside the knowledge files | `search_knowledge` | READ | Passages most relevant to a query, from a local FTS5 index of the registered files. Same allow-list as `read_knowledge_file` |
| `POST /accounts/imap` | — | ADMIN | CLI only: `gigamail accounts add-imap` |
| `GET /accounts/providers` | — | ADMIN | Provider presets inside the CLI |
| `GET /auth/status` | — *(planned: `auth_status`)* | READ | Token state per account (valid/expired), never the token itself |
| `GET /auth/login`, `POST /auth/complete` | — | ADMIN | CLI only: `gigamail login` (Microsoft device flow) |
| `POST /auth/logout` | — | ADMIN | CLI only |
| `GET /addresses`, `GET /addresses/search` | — *(planned: `search_contacts`)* | READ | Address book derived from history |

## 2. Reading mail

| Current endpoint | MCP tool | Class | Notes |
|---|---|---|---|
| `GET /mail` | `list_messages(folder="inbox")` | READ | One tool for every folder |
| `GET /mail/sent` | `list_messages(folder="sent")` | READ | |
| `GET /mail/spam` | `list_messages(folder="spam")` | READ | |
| `GET /mail/deleted` | `list_messages(folder="deleted")` | READ | |
| `GET /mail/drafts` | `list_messages(folder="drafts")` | READ | |
| `GET /mail/folder/{id}` | `list_messages(folder=<id>)` | READ | |
| `GET /mail/unread` | `list_unread` | READ | |
| `GET /mail/unread_count` | — (field of `list_unread`) | — | |
| `GET /mail/{id}` | `read_message` | READ | Full body + attachment list. **Without** `_reply_suggestion` (it was an LLM) |
| `GET /mail/folders` | `list_folders` | READ | |
| `GET /mail/search/{q}` | `search_mail` | READ | Merges provider search and the local index (hybrid) |
| `GET /mail/memory/search` | — (merged into `search_mail`) | — | |
| `GET /mail/sender_history` | `sender_history` | READ | History + sender profile from mail_memory |
| `GET /mail/memory/sender/{email}` | — (merged into `sender_history`) | — | |
| `GET /mail/followup_needed` | — *(planned: `list_followup_needed`)* | READ | Non-LLM heuristic: sent mail with no reply |
| attachments (part of `GET /mail/{id}`) | `read_attachment` | READ | Extracts text (pdfplumber/docx/openpyxl); binaries never reach the agent |
| `GET /mail/memory/stats` | `memory_stats` | READ | State of the local index |
| `GET /observer/stats` | `observer_context` | READ | The user's correction patterns per sender/topic — valuable context for the agent's drafts |
| `GET /health` | — | — | Not needed over stdio |

## 3. Mail actions

| Current endpoint | MCP tool | Class | Notes |
|---|---|---|---|
| `POST /mail/{id}/read` / `unread` | `mark_read` | WRITE_SAFE | `is_read` parameter |
| `POST /mail/{id}/move` | `move_message` | DANGEROUS | MCP two-phase; from the console, Windows Hello / Touch ID check |
| `POST /mail/folders` | `create_folder` | WRITE_SAFE | |
| `DELETE /mail/folders/{id}` | `delete_folder` | DANGEROUS | Two-phase confirmation |
| `POST /mail/send` | `send_mail` | DANGEROUS | Two-phase: preview (to/cc/subject/body/attachments) → token → send |
| `POST /mail/reply_direct` | `reply_mail` | DANGEROUS | Two-phase; quotes the original message |
| `DELETE /mail/{id}` | `delete_message` | DANGEROUS | Two-phase |
| `POST /mail/{id}/spam` / `not_spam` | — *(planned: `mark_spam`)* | DANGEROUS | Two-phase (moves folder, mail can be lost) |
| `POST /snooze`, `GET /snooze/list`, … | — | — | Out of v1 (UI feature); the agent can use its own scheduler |

## 4. Calendar

| Current endpoint | MCP tool | Class | Notes |
|---|---|---|---|
| `GET /calendar`, `GET /calendar/today` | `list_events` | READ | Date range as parameters |
| `POST /calendar` | `create_event` | DANGEROUS | Two-phase (can send invitations to others) |
| `PATCH /calendar/{id}` | — *(planned: `update_event`)* | DANGEROUS | Two-phase |
| `DELETE /calendar/{id}` | `delete_event` | DANGEROUS | Two-phase |
| `POST /calendar/caldav/test|setup`, `DELETE …` | — | ADMIN | CLI only: `gigamail caldav setup` |
| `GET /calendar/caldav/status`, `GET /calendar/primary` | — (field of `list_accounts`) | — | |
| `POST /calendar/primary/{id}` | — | ADMIN | CLI only |

## 5. Privacy / masking

| Current endpoint | MCP tool | Class | Notes |
|---|---|---|---|
| `POST /mask/detect`, `/mask`, `/unmask`, `GET/POST /masks` | — (internal) | — | **Today**: manual masking from the console — you select text and mask it before it goes to the agent; personal masks per account saved in the DB. **Planned**: a transparent filter on the MCP side (every READ output passes through `ade_masker`, `send_mail` unmasks on the way out), switched on per account via CLI |

## 6. Local index

| Current endpoint | MCP tool | Class | Notes |
|---|---|---|---|
| `POST /mail/memory/index` / `stop`, `GET /mail/memory/indexer_state` | — | ADMIN | CLI: `gigamail index` (or lazy indexing on first use). Embeddings are optional: without a key/Ollama, search falls back to FTS keywords, never an error |
| `POST /cache/clear` | — | ADMIN | CLI |

## 7. Outside the MCP surface (and where they went)

These functions **are not MCP tools**. The built-in LLM (`llm.py`) has been
removed; the functions that depended on it now live in the console and are
delegated to the user's agent through `agent_bridge`.

| Function | Where it lives today |
|---|---|
| `generate_draft`, `smart_draft`, `mail_ask`, `sender_summary` | **Console**, delegated to the agent via `agent_bridge`. Not MCP tools: an agent that speaks MCP already has `read_message`, `search_mail`, `get_identity`, `observer_context` and reasons on its own — a "write the draft" tool would be an LLM inside the LLM |
| AI provider setup (`ai_setup`, `openai/auth`) | Removed: no auth towards AI providers, the agent brings the intelligence |
| Voice (`tts`, `voice/transcribe`, `voice/command`) | Out of v1: the agent has its own audio channels |
| Bulk marketing (`bulk/*`) | In the console, out of MCP v1 (candidate for a pro tier) |
| Document generation (`office/excel`, `office/word`) | Out: the agent has its own document tools |
| `files/local`, `identity/extract_from_url` | Removed: filesystem/scraping surface not needed, less risk |
| `snooze/*`, `ui/pending`, `debug/folders` | Console / debug only |

General rule: **the agent gets capabilities, not cognitive shortcuts.**

---

<!-- TOOLMAP:BEGIN (generated by gen_toolmap — do not edit by hand) -->
## Exposed tools (30 — generated from the server)

**READ (18):** `list_accounts`, `get_identity`, `list_knowledge_files`, `read_knowledge_file`, `search_knowledge`, `list_messages`, `list_unread`, `read_message`, `read_attachment`, `list_folders`, `search_mail`, `sender_history`, `observer_context`, `memory_stats`, `list_events`, `find_free_slots`, `drive_list_files`, `drive_read_file`
**WRITE_SAFE (2):** `mark_read`, `create_folder`
**DANGEROUS (10, two-phase):** `move_message`, `send_mail`, `reply_mail`, `delete_message`, `delete_folder`, `create_event`, `delete_event`, `create_zoom_meeting`, `drive_upload_file`, `drive_delete_file`
<!-- TOOLMAP:END -->

Rows marked *(planned)* in the tables above describe the design, not the code: those tools do not exist yet. The box above is generated from the live server, so it lists exactly what the agent can call today.

**CLI only (never MCP):** Microsoft login/logout, add/remove IMAP accounts, CalDAV setup, indexing, masking configuration, data deletion.
Rationale: credentials never travel through the agent channel; a prompt injection in a mail cannot add accounts, exfiltrate tokens or reconfigure the system.

## Design decisions built in

1. **stdio, not HTTP**: the "port 8002 without auth" problem no longer exists.
2. **Optional `account_id` everywhere** (default: all accounts or the active one): no "active account" state the agent can change.
3. **Append-only action log** in `%APPDATA%\ADE\agent_audit.jsonl`: every WRITE_SAFE/DANGEROUS call with timestamp, tool, parameters, outcome. An honest note: append-only means GigaMail does not change past entries, NOT that the file is tamper-proof — anyone with filesystem access can alter it. An integrity chain (hash chaining) will make sense only once there is an external anchor for the head hash.
4. **Anti prompt injection**: mail content is untrusted data. DANGEROUS tools can never confirm themselves: the confirmation token has to be shown to the human by the MCP client (Claude asks for confirmation before running destructive tools — two-phase makes it structural).
5. **PyMuPDF not required**: PDF extraction uses pdfplumber.

---

<a id="italiano"></a>

# GigaMail — Mappa: superficie MCP e classi di rischio

[English](#english) · **Italiano**

Come sono esposte le capacità di GigaMail a un agente, e con quale policy.

**Due superfici, un solo core:**

| Superficie | Chi la usa | Trasporto |
|---|---|---|
| Server MCP | l'agente | **stdio**, nessuna porta di rete |
| Console (opzionale) | l'umano | API HTTP locale su `127.0.0.1`, token di sessione |

Nessun LLM interno in nessuna delle due: il ragionamento è sempre
dell'agente dell'utente (dalla console passa da `agent_bridge`).

Ogni tool ha una **classe di rischio** che determina la policy:

| Classe | Policy | Esempi |
|---|---|---|
| `READ` | libera | lettura, ricerca, elenchi |
| `WRITE_SAFE` | libera + audit log | segna letto, crea cartella |
| `DANGEROUS` | conferma a due fasi + audit log | invio, risposta, cancellazione, eventi calendario |
| `ADMIN` | **solo CLI, mai esposta all'agente** | login, credenziali, gestione account |

La conferma a due fasi funziona così: la prima chiamata (senza `request_id`) NON
esegue e restituisce un'anteprima completa più un `request_id` **inerte** (validità
15 minuti, `GIGAMAIL_APPROVAL_TTL`). L'approvazione avviene **fuori banda** — console,
CLI o Telegram, dietro Windows Hello / Touch ID — mai attraverso l'agente: l'agente
mostra l'anteprima, aspetta che l'umano approvi, poi richiama lo stesso tool con il
`request_id`. Viene eseguito il payload approvato, non quello ripassato dall'agente;
una richiesta approvata e non ancora eseguita si può revocare.

---

## 1. Account

| Endpoint attuale | Tool MCP | Classe | Note |
|---|---|---|---|
| `GET /accounts` | `list_accounts` | READ | Senza dati sensibili (no password/token nel payload) |
| `GET /accounts/active` | — (incluso in `list_accounts`) | — | Flag `active` per account |
| `POST /accounts/active/{id}` | — | — | Non serve: ogni tool accetta `account_id` opzionale |
| `DELETE /accounts/{id}` | — | ADMIN | Solo CLI: `gigamail accounts remove` |
| `GET /accounts/{id}/identity` | `get_identity` | READ | Contesto "chi sono / cosa faccio / tono" utile all'agente per scrivere bozze |
| `POST /accounts/{id}/identity` | — | ADMIN | Solo CLI: `gigamail identity set` (l'agente legge l'identità, non la modifica: una mail ostile non può avvelenarla) |
| `GET /accounts/{id}/identity/files` | `list_knowledge_files` | READ | File di conoscenza registrati dall'utente (listini, condizioni, schede) |
| lettura file identity | `read_knowledge_file` | READ | Estrae il testo di un file registrato. Whitelist = SOLO i percorsi registrati via CLI (`identity add-file`), mai il resto del filesystem |
| ricerca nei file di conoscenza | `search_knowledge` | READ | I passaggi più pertinenti a una domanda, da un indice FTS5 locale dei file registrati. Stessa whitelist di `read_knowledge_file` |
| `POST /accounts/imap` | — | ADMIN | Solo CLI: `gigamail accounts add-imap` |
| `GET /accounts/providers` | — | ADMIN | Preset provider dentro la CLI |
| `GET /auth/status` | — *(pianificato: `auth_status`)* | READ | Stato token per account (valido/scaduto), mai il token stesso |
| `GET /auth/login`, `POST /auth/complete` | — | ADMIN | Solo CLI: `gigamail login` (device flow Microsoft) |
| `POST /auth/logout` | — | ADMIN | Solo CLI |
| `GET /addresses`, `GET /addresses/search` | — *(pianificato: `search_contacts`)* | READ | Rubrica derivata dallo storico |

## 2. Lettura posta

| Endpoint attuale | Tool MCP | Classe | Note |
|---|---|---|---|
| `GET /mail` | `list_messages(folder="inbox")` | READ | Un solo tool per tutte le cartelle |
| `GET /mail/sent` | `list_messages(folder="sent")` | READ | |
| `GET /mail/spam` | `list_messages(folder="spam")` | READ | |
| `GET /mail/deleted` | `list_messages(folder="deleted")` | READ | |
| `GET /mail/drafts` | `list_messages(folder="drafts")` | READ | |
| `GET /mail/folder/{id}` | `list_messages(folder=<id>)` | READ | |
| `GET /mail/unread` | `list_unread` | READ | |
| `GET /mail/unread_count` | — (campo di `list_unread`) | — | |
| `GET /mail/{id}` | `read_message` | READ | Corpo completo + elenco allegati. **Senza** `_reply_suggestion` (era LLM) |
| `GET /mail/folders` | `list_folders` | READ | |
| `GET /mail/search/{q}` | `search_mail` | READ | Unifica ricerca provider + indice locale (ibrida) |
| `GET /mail/memory/search` | — (confluisce in `search_mail`) | — | |
| `GET /mail/sender_history` | `sender_history` | READ | Storico + profilo mittente da mail_memory |
| `GET /mail/memory/sender/{email}` | — (confluisce in `sender_history`) | — | |
| `GET /mail/followup_needed` | — *(pianificato: `list_followup_needed`)* | READ | Euristica non-LLM: mail inviate senza risposta |
| allegati (parte di `GET /mail/{id}`) | `read_attachment` | READ | Estrae testo (pdfplumber/docx/openpyxl); binario mai passato all'agente |
| `GET /mail/memory/stats` | `memory_stats` | READ | Stato dell'indice locale |
| `GET /observer/stats` | `observer_context` | READ | Pattern di correzione dell'utente per mittente/argomento — contesto prezioso per bozze dell'agente |
| `GET /health` | — | — | Non serve su stdio |

## 3. Azioni sulla posta

| Endpoint attuale | Tool MCP | Classe | Note |
|---|---|---|---|
| `POST /mail/{id}/read` / `unread` | `mark_read` | WRITE_SAFE | Parametro `is_read` |
| `POST /mail/{id}/move` | `move_message` | DANGEROUS | Due fasi MCP; dalla console verifica Windows Hello / Touch ID |
| `POST /mail/folders` | `create_folder` | WRITE_SAFE | |
| `DELETE /mail/folders/{id}` | `delete_folder` | DANGEROUS | Conferma a due fasi |
| `POST /mail/send` | `send_mail` | DANGEROUS | Due fasi: anteprima (to/cc/subject/body/allegati) → token → invio |
| `POST /mail/reply_direct` | `reply_mail` | DANGEROUS | Due fasi; quota il messaggio originale |
| `DELETE /mail/{id}` | `delete_message` | DANGEROUS | Due fasi |
| `POST /mail/{id}/spam` / `not_spam` | — *(pianificato: `mark_spam`)* | DANGEROUS | Due fasi (sposta cartella, può far perdere mail) |
| `POST /snooze`, `GET /snooze/list`, … | — | — | Fuori v1 (feature UI); l'agente può usare il proprio scheduler |

## 4. Calendario

| Endpoint attuale | Tool MCP | Classe | Note |
|---|---|---|---|
| `GET /calendar`, `GET /calendar/today` | `list_events` | READ | Range date come parametri |
| `POST /calendar` | `create_event` | DANGEROUS | Due fasi (può generare inviti ad altri) |
| `PATCH /calendar/{id}` | — *(pianificato: `update_event`)* | DANGEROUS | Due fasi |
| `DELETE /calendar/{id}` | `delete_event` | DANGEROUS | Due fasi |
| `POST /calendar/caldav/test|setup`, `DELETE …` | — | ADMIN | Solo CLI: `gigamail caldav setup` |
| `GET /calendar/caldav/status`, `GET /calendar/primary` | — (campo di `list_accounts`) | — | |
| `POST /calendar/primary/{id}` | — | ADMIN | Solo CLI |

## 5. Privacy / masking

| Endpoint attuale | Tool MCP | Classe | Note |
|---|---|---|---|
| `POST /mask/detect`, `/mask`, `/unmask`, `GET/POST /masks` | — (interno) | — | **Oggi**: masking manuale dalla console — selezioni il testo, lo mascheri prima di passarlo all'agente; maschere personali per account salvate nel DB. **Pianificato**: filtro trasparente sul lato MCP (ogni output READ passa da `ade_masker`, `send_mail` smaschera in uscita) con attivazione per account via CLI |

## 6. Indice locale

| Endpoint attuale | Tool MCP | Classe | Note |
|---|---|---|---|
| `POST /mail/memory/index` / `stop`, `GET /mail/memory/indexer_state` | — | ADMIN | CLI: `gigamail index` (o indicizzazione lazy al primo uso). Embedding opzionali: senza chiave/Ollama la ricerca degrada a FTS keyword, mai errore |
| `POST /cache/clear` | — | ADMIN | CLI |

## 7. Fuori dalla superficie MCP (e dove sono finite)

Queste funzioni **non sono tool MCP**. L'LLM interno (`llm.py`) è stato
eliminato; le funzioni che dipendevano da lui vivono ora nella console e
sono delegate all'agente dell'utente tramite `agent_bridge`.

| Funzione | Dove sta oggi |
|---|---|
| `generate_draft`, `smart_draft`, `mail_ask`, `sender_summary` | **Console**, delegati all'agente via `agent_bridge`. Non tool MCP: un agente che parla MCP ha già `read_message`, `search_mail`, `get_identity`, `observer_context` e ragiona da sé — un tool "scrivi la bozza" sarebbe un LLM dentro l'LLM |
| Setup fornitori AI (`ai_setup`, `openai/auth`) | Rimossi: nessuna auth verso fornitori AI, l'intelligenza la porta l'agente |
| Voce (`tts`, `voice/transcribe`, `voice/command`) | Fuori v1: l'agente ha i propri canali audio |
| Marketing bulk (`bulk/*`) | Presente in console, fuori dalla v1 MCP (candidato a tier pro) |
| Generazione documenti (`office/excel`, `office/word`) | Fuori: l'agente ha i propri strumenti documento |
| `files/local`, `identity/extract_from_url` | Rimossi: superficie filesystem/scraping non necessaria, riduce il rischio |
| `snooze/*`, `ui/pending`, `debug/folders` | Solo console / debug |

Regola generale: **l'agente riceve capacità, non scorciatoie cognitive.**

---

<!-- TOOLMAP-IT:BEGIN (generated by gen_toolmap — do not edit by hand) -->
## Riepilogo tool esposti (30 — generato dal server)

**READ (18):** `list_accounts`, `get_identity`, `list_knowledge_files`, `read_knowledge_file`, `search_knowledge`, `list_messages`, `list_unread`, `read_message`, `read_attachment`, `list_folders`, `search_mail`, `sender_history`, `observer_context`, `memory_stats`, `list_events`, `find_free_slots`, `drive_list_files`, `drive_read_file`
**WRITE_SAFE (2):** `mark_read`, `create_folder`
**DANGEROUS (10, due fasi):** `move_message`, `send_mail`, `reply_mail`, `delete_message`, `delete_folder`, `create_event`, `delete_event`, `create_zoom_meeting`, `drive_upload_file`, `drive_delete_file`
<!-- TOOLMAP-IT:END -->

Le righe marcate *(pianificato)* nelle tabelle sopra descrivono il disegno, non il codice: quei tool non esistono ancora. Il riquadro qui sopra e' generato dal server vivo, quindi elenca esattamente cio' che l'agente puo' chiamare oggi.

**Solo CLI (mai MCP):** login/logout Microsoft, add/remove account IMAP, setup CalDAV, indicizzazione, masking config, cancellazione dati.
Razionale: le credenziali non transitano mai nel canale agente; un prompt injection in una mail non può aggiungere account, esfiltrare token o riconfigurare il sistema.

## Decisioni di design incorporate

1. **stdio, non HTTP**: il problema "porta 8002 senza auth" cessa di esistere.
2. **`account_id` opzionale ovunque** (default: tutti gli account o l'attivo): niente stato "account attivo" mutabile dall'agente.
3. **Registro azioni** append-only in `%APPDATA%\ADE\agent_audit.jsonl`: ogni chiamata WRITE_SAFE/DANGEROUS con timestamp, tool, parametri, esito. Nota di onestà: append-only significa che GigaMail non modifica le entry passate, NON che il file sia tamper-proof — chi ha accesso al filesystem può alterarlo. Una catena di integrità (hash chaining) avrà senso solo quando esisterà un ancoraggio esterno per l'hash di testa.
4. **Anti prompt-injection**: il contenuto delle mail è dato non fidato. I tool DANGEROUS non sono mai auto-confermabili: il token di conferma va mostrato all'umano dal client MCP (Claude chiede conferma prima di eseguire tool distruttivi — il two-phase lo rende strutturale).
5. **PyMuPDF non richiesto**: l'estrazione PDF usa pdfplumber.
