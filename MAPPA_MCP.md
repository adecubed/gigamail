# ADE Mail Agent — Mappa endpoint FastAPI → tool MCP

Versione agent-only: niente LLM interno, niente UI, trasporto **stdio** (nessuna porta HTTP).
Ogni tool ha una **classe di rischio** che determina la policy:

| Classe | Policy | Esempi |
|---|---|---|
| `READ` | libera | lettura, ricerca, elenchi |
| `WRITE_SAFE` | libera + audit log | segna letto, sposta in cartella |
| `DANGEROUS` | conferma a due fasi + audit log | invio, cancellazione, spam |
| `ADMIN` | **solo CLI, mai esposta all'agente** | login, credenziali, gestione account |

La conferma a due fasi funziona così: la prima chiamata (senza token) NON esegue e
restituisce un'anteprima completa + `confirm_token` monouso (validità 5 minuti);
l'agente mostra l'anteprima all'umano e riesegue con il token per confermare.

---

## 1. Account

| Endpoint attuale | Tool MCP | Classe | Note |
|---|---|---|---|
| `GET /accounts` | `list_accounts` | READ | Senza dati sensibili (no password/token nel payload) |
| `GET /accounts/active` | — (incluso in `list_accounts`) | — | Flag `active` per account |
| `POST /accounts/active/{id}` | — | — | Non serve: ogni tool accetta `account_id` opzionale |
| `DELETE /accounts/{id}` | — | ADMIN | Solo CLI: `ade-mail-agent accounts remove` |
| `GET /accounts/{id}/identity` | `get_identity` | READ | Contesto "chi sono / cosa faccio / tono" utile all'agente per scrivere bozze |
| `POST /accounts/{id}/identity` | — | ADMIN | Solo CLI: `ade-mail-agent identity set` (l'agente legge l'identità, non la modifica: una mail ostile non può avvelenarla) |
| `GET /accounts/{id}/identity/files` | `list_knowledge_files` | READ | File di conoscenza registrati dall'utente (listini, condizioni, schede) |
| lettura file identity | `read_knowledge_file` | READ | Estrae il testo di un file registrato. Whitelist = SOLO i percorsi registrati via CLI (`identity add-file`), mai il resto del filesystem |
| `POST /accounts/imap` | — | ADMIN | Solo CLI: `ade-mail-agent accounts add-imap` |
| `GET /accounts/providers` | — | ADMIN | Preset provider dentro la CLI |
| `GET /auth/status` | `auth_status` | READ | Stato token per account (valido/scaduto), mai il token stesso |
| `GET /auth/login`, `POST /auth/complete` | — | ADMIN | Solo CLI: `ade-mail-agent login` (device flow Microsoft) |
| `POST /auth/logout` | — | ADMIN | Solo CLI |
| `GET /addresses`, `GET /addresses/search` | `search_contacts` | READ | Rubrica derivata dallo storico |

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
| `GET /mail/followup_needed` | `list_followup_needed` | READ | Euristica non-LLM: mail inviate senza risposta |
| allegati (parte di `GET /mail/{id}`) | `read_attachment` | READ | Estrae testo (pdfplumber/docx/openpyxl); binario mai passato all'agente |
| `GET /mail/memory/stats` | `memory_stats` | READ | Stato dell'indice locale |
| `GET /observer/stats` | `observer_context` | READ | Pattern di correzione dell'utente per mittente/argomento — contesto prezioso per bozze dell'agente |
| `GET /health` | — | — | Non serve su stdio |

## 3. Azioni sulla posta

| Endpoint attuale | Tool MCP | Classe | Note |
|---|---|---|---|
| `POST /mail/{id}/read` / `unread` | `mark_read` | WRITE_SAFE | Parametro `is_read` |
| `POST /mail/{id}/move` | `move_message` | WRITE_SAFE | Reversibile |
| `POST /mail/folders` | `create_folder` | WRITE_SAFE | |
| `DELETE /mail/folders/{id}` | `delete_folder` | DANGEROUS | Conferma a due fasi |
| `POST /mail/send` | `send_mail` | DANGEROUS | Due fasi: anteprima (to/cc/subject/body/allegati) → token → invio |
| `POST /mail/reply_direct` | `reply_mail` | DANGEROUS | Due fasi; quota il messaggio originale |
| `DELETE /mail/{id}` | `delete_message` | DANGEROUS | Due fasi |
| `POST /mail/{id}/spam` / `not_spam` | `mark_spam` | DANGEROUS | Due fasi (sposta cartella, può far perdere mail) |
| `POST /snooze`, `GET /snooze/list`, … | — | — | Fuori v1 (feature UI); l'agente può usare il proprio scheduler |

## 4. Calendario

| Endpoint attuale | Tool MCP | Classe | Note |
|---|---|---|---|
| `GET /calendar`, `GET /calendar/today` | `list_events` | READ | Range date come parametri |
| `POST /calendar` | `create_event` | DANGEROUS | Due fasi (può generare inviti ad altri) |
| `PATCH /calendar/{id}` | `update_event` | DANGEROUS | Due fasi |
| `DELETE /calendar/{id}` | `delete_event` | DANGEROUS | Due fasi |
| `POST /calendar/caldav/test|setup`, `DELETE …` | — | ADMIN | Solo CLI: `ade-mail-agent caldav setup` |
| `GET /calendar/caldav/status`, `GET /calendar/primary` | — (campo di `list_accounts`) | — | |
| `POST /calendar/primary/{id}` | — | ADMIN | Solo CLI |

## 5. Privacy / masking

| Endpoint attuale | Tool MCP | Classe | Note |
|---|---|---|---|
| `POST /mask/detect`, `/mask`, `/unmask`, `GET/POST /masks` | — (interno) | — | Non tool: **filtro trasparente**. Se il masking è attivo (config), ogni output READ passa da `ade_masker` prima di arrivare all'agente; `send_mail` smaschera in uscita. Configurazione via CLI |

## 6. Indice locale

| Endpoint attuale | Tool MCP | Classe | Note |
|---|---|---|---|
| `POST /mail/memory/index` / `stop`, `GET /mail/memory/indexer_state` | — | ADMIN | CLI: `ade-mail-agent index` (o indicizzazione lazy al primo uso). Embedding opzionali: senza chiave/Ollama la ricerca degrada a FTS keyword, mai errore |
| `POST /cache/clear` | — | ADMIN | CLI |

## 7. Eliminati del tutto (con motivo)

| Endpoint | Motivo |
|---|---|
| `POST /mail/generate_draft`, `/reply_draft`, `/smart_draft`, `/suggest_reply`, `/reply_natural`, `POST /mail/sender_summary`, `GET /mail/{id}/summary`, `POST /mail_ask` | LLM interno: nella versione agent l'intelligenza è dell'agente. `observer_context` + `sender_history` + `get_identity` gli danno il contesto per fare le stesse cose meglio |
| `GET /mail/{id}/tts`, `GET /calendar/today/tts`, `POST /tts`, `POST /voice/transcribe`, `POST /voice/command` | Voce: canale dell'agente, non nostro |
| `POST /ai_setup/*`, `GET/POST /openai/auth/*` | Auth verso fornitori AI: sparisce con l'LLM |
| `POST /bulk/*` | Marketing bulk con AI: fuori scope v1 (candidata a tier pro futuro) |
| `POST /office/excel`, `/office/word` | L'agente ha i propri strumenti documento |
| `GET /mail/{id}/folder_suggestion` | Basata su LLM |
| `GET /files/local`, `POST /identity/extract_from_url` | Superficie filesystem/scraping non necessaria; riduce rischio |
| `GET /ui/pending`, `GET /mail/debug/folders` | UI/debug |

---

<!-- TOOLMAP:BEGIN (generato da gen_toolmap — non editare a mano) -->
## Riepilogo tool esposti (24 — generato dal server)

**READ (15):** `list_accounts`, `get_identity`, `list_knowledge_files`, `read_knowledge_file`, `list_messages`, `list_unread`, `read_message`, `read_attachment`, `list_folders`, `search_mail`, `sender_history`, `observer_context`, `memory_stats`, `list_events`, `find_free_slots`
**WRITE_SAFE (3):** `mark_read`, `move_message`, `create_folder`
**DANGEROUS (6, due fasi):** `send_mail`, `reply_mail`, `delete_message`, `delete_folder`, `create_event`, `delete_event`
<!-- TOOLMAP:END -->

In mappa ma non ancora implementati: `auth_status`, `search_contacts`, `list_followup_needed` (READ), `mark_spam`, `update_event` (DANGEROUS).

**Solo CLI (mai MCP):** login/logout Microsoft, add/remove account IMAP, setup CalDAV, indicizzazione, masking config, cancellazione dati.
Razionale: le credenziali non transitano mai nel canale agente; un prompt injection in una mail non può aggiungere account, esfiltrare token o riconfigurare il sistema.

## Decisioni di design incorporate

1. **stdio, non HTTP**: il problema "porta 8002 senza auth" cessa di esistere.
2. **`account_id` opzionale ovunque** (default: tutti gli account o l'attivo): niente stato "account attivo" mutabile dall'agente.
3. **Registro azioni** append-only in `%APPDATA%\ADE\agent_audit.jsonl`: ogni chiamata WRITE_SAFE/DANGEROUS con timestamp, tool, parametri, esito. Nota di onestà: append-only significa che GigaMail non modifica le entry passate, NON che il file sia tamper-proof — chi ha accesso al filesystem può alterarlo. Una catena di integrità (hash chaining) avrà senso solo quando esisterà un ancoraggio esterno per l'hash di testa.
4. **Anti prompt-injection**: il contenuto delle mail è dato non fidato. I tool DANGEROUS non sono mai auto-confermabili: il token di conferma va mostrato all'umano dal client MCP (Claude chiede conferma prima di eseguire tool distruttivi — il two-phase lo rende strutturale).
5. **PyMuPDF assente** → licenza libera (MIT/Apache) possibile: l'estrazione PDF usa pdfplumber.
