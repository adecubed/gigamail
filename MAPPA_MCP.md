# GigaMail — Mappa: superficie MCP e classi di rischio

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
| `WRITE_SAFE` | libera + audit log | segna letto, sposta in cartella |
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
| `POST /mail/{id}/move` | `move_message` | WRITE_SAFE | Reversibile |
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

<!-- TOOLMAP:BEGIN (generato da gen_toolmap — non editare a mano) -->
## Riepilogo tool esposti (24 — generato dal server)

**READ (15):** `list_accounts`, `get_identity`, `list_knowledge_files`, `read_knowledge_file`, `list_messages`, `list_unread`, `read_message`, `read_attachment`, `list_folders`, `search_mail`, `sender_history`, `observer_context`, `memory_stats`, `list_events`, `find_free_slots`
**WRITE_SAFE (3):** `mark_read`, `move_message`, `create_folder`
**DANGEROUS (6, due fasi):** `send_mail`, `reply_mail`, `delete_message`, `delete_folder`, `create_event`, `delete_event`
<!-- TOOLMAP:END -->

Le righe marcate *(pianificato)* nelle tabelle sopra descrivono il disegno, non il codice: quei tool non esistono ancora. Il riquadro qui sopra e' generato dal server vivo, quindi elenca esattamente cio' che l'agente puo' chiamare oggi.

**Solo CLI (mai MCP):** login/logout Microsoft, add/remove account IMAP, setup CalDAV, indicizzazione, masking config, cancellazione dati.
Razionale: le credenziali non transitano mai nel canale agente; un prompt injection in una mail non può aggiungere account, esfiltrare token o riconfigurare il sistema.

## Decisioni di design incorporate

1. **stdio, non HTTP**: il problema "porta 8002 senza auth" cessa di esistere.
2. **`account_id` opzionale ovunque** (default: tutti gli account o l'attivo): niente stato "account attivo" mutabile dall'agente.
3. **Registro azioni** append-only in `%APPDATA%\ADE\agent_audit.jsonl`: ogni chiamata WRITE_SAFE/DANGEROUS con timestamp, tool, parametri, esito. Nota di onestà: append-only significa che GigaMail non modifica le entry passate, NON che il file sia tamper-proof — chi ha accesso al filesystem può alterarlo. Una catena di integrità (hash chaining) avrà senso solo quando esisterà un ancoraggio esterno per l'hash di testa.
4. **Anti prompt-injection**: il contenuto delle mail è dato non fidato. I tool DANGEROUS non sono mai auto-confermabili: il token di conferma va mostrato all'umano dal client MCP (Claude chiede conferma prima di eseguire tool distruttivi — il two-phase lo rende strutturale).
5. **PyMuPDF non richiesto**: l'estrazione PDF usa pdfplumber.
