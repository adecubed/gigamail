/**
 * i18n.js — Internazionalizzazione GIGA Mail (IT default + EN).
 *
 * Modello: l'italiano resta scritto nell'HTML (fallback naturale).
 * Gli elementi traducibili hanno data-i18n="chiave" (per il testo),
 * data-i18n-ph="chiave" (per placeholder) o data-i18n-title="chiave" (per title).
 * applyLang(lang) scansiona il DOM e sostituisce SOLO se lang === 'en'.
 * Tornando a 'it' ripristina i testi italiani originali dal dizionario.
 *
 * La scelta è salvata in localStorage (ade_lang). Default: 'it'.
 */
(function () {
  const DICT = {
    it: {
      // finestra / toolbar comuni
      hide: "Nascondi", fullscreen: "Tutto schermo", close: "Chiudi",
      cancel: "Annulla", save: "Salva", create: "Crea", optional: "(opzionale)",
      loading: "Caricamento…", refresh: "Aggiorna",
      // ask window
      ask_title: "Chiedi alle mail",
      ask_example: 'Es: "trova le mail dove ho parlato di Cézanne" poi "fammi un riassunto"',
      ask_placeholder: "Chiedi qualcosa sulle tue mail…",
      ask_empty_title: "Chiedimi qualcosa sulle tue mail.",
      searching: "Sto cercando…", no_answer: "(nessuna risposta)",
      error: "Errore", from_label: "Da",
      // calendario
      cal_title: "GIGA Calendario", cal_edit: "Modifica", cal_followup: "Follow up",
      cal_delete: "Cancella", cal_upcoming: "Prossimi appuntamenti",
      cal_all: "Tutti", cal_today: "Oggi", cal_next7: "Prossimi 7 giorni",
      cal_new_event: "Nuovo evento", cal_edit_event: "Modifica evento", cal_event: "Evento",
      title_label: "Titolo", start_label: "Inizio", end_label: "Fine",
      place_label: "Luogo", notes_label: "Note", invite_label: "Invita",
      attendees_label: "Partecipanti", event_title_ph: "Titolo evento…",
      no_upcoming: "Nessun appuntamento in arrivo",
      // sidebar / vista principale
      inbox: "Posta in arrivo", calendar: "Calendario",
      sent_items: "Inviati", drafts: "Bozze", marketing: "Marketing",
      account_label: "Account", account_load_error: "Errore caricamento account",
      history_with: "mail con", history_sent: "inviate", history_received: "ricevute",
      history_themes: "Temi", history_summarize: "Riassumi storico",
      history_summarizing: "Riassumo…", history_no_summary: "Nessun riassunto disponibile.",
      history_summary_error: "Errore nel riassunto.",
      refresh_folders: "Aggiorna cartelle", voice_command: "Comando vocale",
      spam: "Spam", trash: "Cestino", compact_mode: "Modalità compatta",
      search_mail_ph: "Cerca mail…", snoozed: "Snoozed",
      refresh_mail_title: "Aggiorna mail + Refresh identity",
      // marketing
      marketing_mail: "Marketing Mail", subject_ph: "Oggetto…",
      pause_sec: "PAUSA (sec)", vars_hint: "Variabili: {nome}, {email}",
      bulk_instruction_ph: "Descrivi la mail da generare con AI…",
      plain_text_ph: "Testo semplice…", waiting: "In attesa…",
      images_label: "IMMAGINI:", insert: "Inserisci",
      pause_between: "Pausa tra invii (sec)", subject_mail_ph: "Oggetto della mail…",
      load_recipients_first: "Carica prima un file con i destinatari",
      bulk_write_instructions: "Scrivi prima le istruzioni per il LLM",
      bulk_generating: "Generazione in corso...", bulk_draft_generated: "Bozza generata!",
      bulk_generated_ok: "Generato — controlla e modifica prima di inviare",
      insert_subject: "Inserisci l'oggetto della mail", write_body: "Scrivi il corpo della mail",
      bulk_started: "Invio bulk avviato!",
      bulk_stop_requested: "Stop richiesto — attendi completamento mail in corso",
      no_subject: "(nessun oggetto)", sending_to: "Invio a", in_progress: "In corso...",
      completed_ok: "Completato",
      // reply / nuova mail
      mail_generic: "ADE Mail", new_reply: "Nuova risposta", new_mail: "Nuova mail",
      to_label: "A:", cc_label: "CC:", bcc_label: "BCC:", subject_label: "Oggetto:",
      reply_text_ph: "Scrivi la tua risposta…",
      reply_text_drag_ph: "Scrivi la tua risposta… (trascina file o immagini qui)",
      new_mail_body_ph: "Scrivi la mail… (trascina file o immagini qui)",
      new_mail_body_simple_ph: "Scrivi la mail…",
      ai_instruction_ph: "Istruzione AI…",
      ai_instruction_drag_ph: "Istruzione AI — trascina file per contesto…",
      send: "Invia ↑", recipient_ph: "destinatario@email.it",
      attach_file: "Allega file", followup: "Follow-up",
      mask_title: "Maschera dati sensibili (CF, IBAN, email…)",
      // account
      add_account: "Aggiungi account", name_label: "Nome", email_label: "Email",
      password_label: "Password", provider_label: "Provider", custom: "Personalizzato",
      connect_imap: "Connetti IMAP", example_work: "Es: Lavoro",
      ms_login: "Microsoft 365 — Login",
      ms_login_desc: "Clicca per avviare l'autenticazione Microsoft 365 via browser.",
      ms_goto: "Vai su questo indirizzo nel browser:",
      ms_enter_code: "Inserisci il codice:",
      ms_after_code: "Dopo aver inserito il codice nel browser, clicca qui:",
      open_ms_login: "Apri pagina login Microsoft",
      // cartelle
      new_folder: "Nuova cartella", keywords_label: "Parole chiave",
      example_clients: "Es: Clienti", example_kw: "Es: fattura, cliente",
      move_mail: "Sposta mail", folder_label: "Cartella", move: "Sposta",
      // snooze
      snooze_tonight: "Stasera 18:00", snooze_tomorrow: "Domani mattina",
      snooze_monday: "Lunedì prossimo", snooze_nextweek: "Settimana prossima",
      snooze_custom: "Snooze personalizzato", date_time_label: "Data e ora",
      snooze: "Snooze",
      // automazioni (0.2.1)
      automations: "Automazioni",
      automations_sub: "risposte semi-auto e auto, dietro Windows Hello",
      rules_title: "Regole di risposta", rule_new: "Nuova regola",
      rule_account: "Account", rule_trigger: "Trigger",
      rule_trigger_senders: "Mittenti (indirizzi)", rule_trigger_folder: "Cartella (mittente qualsiasi)",
      rule_folder_warn: "Cartella = mittente arbitrario: restano le barriere anti-spam e il primo contatto passa sempre da te.",
      rule_style: "Stile / istruzioni", rule_style_ph: "es. cordiale e breve; rispondi nella lingua del mittente",
      rule_docs: "Documenti (uniche fonti della bozza)", rule_docs_pick: "📎 Aggiungi documento…",
      rule_mode: "Modalità", rule_mode_semi: "Semi — approvo ogni invio", rule_mode_auto: "Auto — invia da sola, entro i limiti",
      rule_first_contact: "Primo contatto", rule_fc_semi: "sempre approvato da me", rule_fc_auto: "auto anche al primo messaggio",
      rule_cap: "Max/giorno", rule_cooldown: "Cooldown (h)", rule_expiry: "Scade tra (giorni)",
      rule_hello_hint: "La conferma finale è Windows Hello: una regola è una pre-approvazione.",
      rule_create: "Crea regola",
      watch_title: "Watcher",
      watch_desc: "Il processo che legge la posta, applica le regole e fa scrivere la bozza al tuo agente. Senza, le regole non fanno nulla.",
      watch_start: "▶ Avvia", watch_stop: "■ Ferma",
      notify_title: "Notifiche e agente", agent_title: "Agente che scrive le bozze",
      agent_desc: "GigaMail non ha un LLM interno: le bozze le scrive il tuo agente (default: Claude Code, `claude -p`). Cambialo in agent.json.",
      consent_title: "Verifica umana (Hello / Touch ID)", desktop_title: "Notifiche sul PC",
      desktop_setup: "Attiva bottoni (UAC)",
      telegram_hint: "Si configura dal terminale (il token del bot non passa da questa finestra): gigamail telegram setup, con --approve per approvare dal telefono (Hello).",
      login: "Login",
      // mail detail / liste
      no_mail: "Nessuna mail.", delete: "Elimina",
      reply_to: "Rispondi a", attach_opts_title: "Click: apri • Tasto destro: opzioni",
      dock_back: "Riporta nella console",
      use_draft: "USA QUESTA BOZZA", ignore: "IGNORA",
      open_in_window: "Apri in finestra", ade_voice: "ADE voice",
      no_event_period: "Nessun evento nel periodo.",
      close_upper: "CHIUDI", no_account: "Nessun account",
      reply_subject_ph: "Oggetto risposta...",
      cancel_upper: "ANNULLA", new_reply_upper: "NUOVA RISPOSTA",
      select_attach_auto: "Seleziona i file da allegare automaticamente",
      add_note_ph: "Aggiungi nota… o trascina un file",
      reactivate: "Riattiva", done: "Fatto", completed: "Completati",
      // suggerimento cartella
      folder_suggestion: "SUGGERIMENTO CARTELLA",
      yes_move: "SÌ, SPOSTA", no: "NO",
      no_personal_folder: "Nessuna cartella personale.",
      no_folder_avail: "Nessuna cartella disponibile",
      config_folder_identity: "Configura identity cartella",
      delete_folder: "Elimina cartella",
      unread: "Non lette", sent_today: "Inviate oggi",
      goto_account: "Vai all'account →", open_calendar: "Apri calendario →",
      no_calendar: "Nessun calendario configurato",
      new_mail_badge: "NUOVA MAIL",
      // identity
      identity_folder: "IDENTITY CARTELLA",
      identity_folder_sub: "sovrascrive identity account per questa cartella",
      who_here: "CHI SEI IN QUESTA CARTELLA", what_you_do: "COSA FAI",
      tone: "TONO", folder_info: "INFO SPECIFICHE CARTELLA",
      identity_account: "IDENTITÀ ACCOUNT", who_you_are: "CHI SEI",
      tone_reply: "TONO DI RISPOSTA",
      key_info: "INFORMAZIONI CHIAVE", key_info_sub: "(prezzi, orari, contatti...)",
      extract_url: "ESTRAI DA URL", extract_url_sub: "(sito, LinkedIn, pagina prodotto...)",
      useful_files: "FILE UTILI", useful_files_sub: "(.txt .md .csv — es. listino prezzi)",
      folder_btn: "📁 CARTELLA", pick_folder: "Seleziona cartella",
      folder_word: "CARTELLA", save_upper: "SALVA",
      recent_unread_5d: "Mail recenti non lette negli ultimi 5 giorni",
      preview_identity: "PREVIEW IDENTITY ESTRATTA",
      preview_identity_sub: "Modifica se necessario, poi conferma per applicare ai campi.",
      info_key: "INFO CHIAVE",
      who_ph: "Lascia vuoto per usare identity account",
      whatdo_ph: "Es: Rispondo a lead Idealista",
      tone_ph: "Es: Commerciale, veloce, diretto",
      folder_info_ph: "Info specifiche per questa cartella...",
      // lingua
      lang_switch_title: "Lingua / Language",
      // bottoni azione mail (icona + parola maiuscola)
      listen: "ASCOLTA", reply_upper: "RISPONDI", all_upper: "TUTTI",
      forward_upper: "INOLTRA", summarize_upper: "RIASSUMI", move_upper: "SPOSTA",
      not_spam_upper: "NON È SPAM", spam_upper: "SPAM", unread_upper: "NON LETTA",
      delete_upper: "ELIMINA",
      press_summarize: "Premi RIASSUMI per generare il riassunto.",
      listen_cap: "Ascolta", reply_cap: "Rispondi", forward_cap: "Inoltra",
      summarize_cap: "Riassumi", spam_cap: "Spam", delete_cap: "Elimina",
      move_to_spam: "Spostare in spam?", delete_this_mail: "Eliminare questa mail?",
      add_account_btn: "+ Account", add_folder_btn: "+ Cartella",
      recipients: "Destinatari", subject_word: "Oggetto", format_word: "Formato",
      load_csv: "Carica CSV / Excel", preview: "Preview",
      to_word: "A", ai_instruction_word: "Istruzione AI",
      who_account_ph: "Es: Ufficio Vendite Progetto 20128 Milano",
      whatdo_account_ph: "Es: Rispondo a richieste su appartamenti",
      tone_account_ph: "Es: Professionale, cordiale, italiano formale",
      url_ph: "https://... oppure incolla testo con URL",
      start_send: "Avvia invio", stop_send: "Ferma invio",
      generate: "GENERA",
      drag_image: "Trascina immagine qui", load_folder: "Carica cartella",
    },
    en: {
      hide: "Hide", fullscreen: "Fullscreen", close: "Close",
      cancel: "Cancel", save: "Save", create: "Create", optional: "(optional)",
      loading: "Loading…", refresh: "Refresh",
      ask_title: "Ask your mail",
      ask_example: 'E.g.: "find emails where I talked about Cézanne" then "summarize"',
      ask_placeholder: "Ask something about your emails…",
      ask_empty_title: "Ask me anything about your emails.",
      searching: "Searching…", no_answer: "(no answer)",
      error: "Error", from_label: "From",
      cal_title: "GIGA Calendar", cal_edit: "Edit", cal_followup: "Follow up",
      cal_delete: "Delete", cal_upcoming: "Upcoming events",
      cal_all: "All", cal_today: "Today", cal_next7: "Next 7 days",
      cal_new_event: "New event", cal_edit_event: "Edit event", cal_event: "Event",
      title_label: "Title", start_label: "Start", end_label: "End",
      place_label: "Location", notes_label: "Notes", invite_label: "Invite",
      attendees_label: "Attendees", event_title_ph: "Event title…",
      no_upcoming: "No upcoming events",
      inbox: "Inbox", calendar: "Calendar",
      sent_items: "Sent", drafts: "Drafts", marketing: "Marketing",
      account_label: "Account", account_load_error: "Error loading accounts",
      history_with: "emails with", history_sent: "sent", history_received: "received",
      history_themes: "Topics", history_summarize: "Summarize history",
      history_summarizing: "Summarizing…", history_no_summary: "No summary available.",
      history_summary_error: "Summary error.",
      refresh_folders: "Refresh folders", voice_command: "Voice command",
      spam: "Spam", trash: "Trash", compact_mode: "Compact mode",
      search_mail_ph: "Search mail…", snoozed: "Snoozed",
      refresh_mail_title: "Refresh mail + identity",
      marketing_mail: "Marketing Mail", subject_ph: "Subject…",
      pause_sec: "PAUSE (sec)", vars_hint: "Variables: {nome}, {email}",
      bulk_instruction_ph: "Describe the email to generate with AI…",
      plain_text_ph: "Plain text…", waiting: "Waiting…",
      images_label: "IMAGES:", insert: "Insert",
      pause_between: "Pause between sends (sec)", subject_mail_ph: "Email subject…",
      load_recipients_first: "Load a recipients file first",
      bulk_write_instructions: "Write the instructions for the LLM first",
      bulk_generating: "Generating...", bulk_draft_generated: "Draft generated!",
      bulk_generated_ok: "Generated — review and edit before sending",
      insert_subject: "Enter the email subject", write_body: "Write the email body",
      bulk_started: "Bulk send started!",
      bulk_stop_requested: "Stop requested — wait for the current email to finish",
      no_subject: "(no subject)", sending_to: "Sending to", in_progress: "In progress...",
      completed_ok: "Completed",
      mail_generic: "ADE Mail", new_reply: "New reply", new_mail: "New mail",
      to_label: "To:", cc_label: "CC:", bcc_label: "BCC:", subject_label: "Subject:",
      reply_text_ph: "Write your reply…",
      reply_text_drag_ph: "Write your reply… (drag files or images here)",
      new_mail_body_ph: "Write your email… (drag files or images here)",
      new_mail_body_simple_ph: "Write your email…",
      ai_instruction_ph: "AI instruction…",
      ai_instruction_drag_ph: "AI instruction — drag files for context…",
      send: "Send ↑", recipient_ph: "recipient@email.com",
      attach_file: "Attach file", followup: "Follow-up",
      mask_title: "Mask sensitive data (tax code, IBAN, email…)",
      add_account: "Add account", name_label: "Name", email_label: "Email",
      password_label: "Password", provider_label: "Provider", custom: "Custom",
      connect_imap: "Connect IMAP", example_work: "E.g.: Work",
      ms_login: "Microsoft 365 — Login",
      ms_login_desc: "Click to start Microsoft 365 authentication via browser.",
      ms_goto: "Go to this address in your browser:",
      ms_enter_code: "Enter the code:",
      ms_after_code: "After entering the code in the browser, click here:",
      open_ms_login: "Open Microsoft login page",
      new_folder: "New folder", keywords_label: "Keywords",
      example_clients: "E.g.: Clients", example_kw: "E.g.: invoice, client",
      move_mail: "Move mail", folder_label: "Folder", move: "Move",
      snooze_tonight: "Tonight 6:00 PM", snooze_tomorrow: "Tomorrow morning",
      snooze_monday: "Next Monday", snooze_nextweek: "Next week",
      snooze_custom: "Custom snooze", date_time_label: "Date and time",
      snooze: "Snooze",
      automations: "Automations",
      automations_sub: "semi-auto and auto replies, behind Windows Hello",
      rules_title: "Reply rules", rule_new: "New rule",
      rule_account: "Account", rule_trigger: "Trigger",
      rule_trigger_senders: "Senders (addresses)", rule_trigger_folder: "Folder (any sender)",
      rule_folder_warn: "Folder = arbitrary sender: the anti-spam barriers stay in front and a first contact always goes through you.",
      rule_style: "Style / instructions", rule_style_ph: "e.g. friendly and short; reply in the sender's language",
      rule_docs: "Documents (the draft's only sources)", rule_docs_pick: "📎 Add document…",
      rule_mode: "Mode", rule_mode_semi: "Semi — I approve every send", rule_mode_auto: "Auto — sends by itself, within limits",
      rule_first_contact: "First contact", rule_fc_semi: "always approved by me", rule_fc_auto: "auto even on the first message",
      rule_cap: "Max/day", rule_cooldown: "Cooldown (h)", rule_expiry: "Expires in (days)",
      rule_hello_hint: "The final confirmation is Windows Hello: a rule is a pre-approval.",
      rule_create: "Create rule",
      watch_title: "Watcher",
      watch_desc: "The process that reads mail, applies the rules and has your agent write the draft. Without it, rules do nothing.",
      watch_start: "▶ Start", watch_stop: "■ Stop",
      notify_title: "Notifications and agent", agent_title: "Agent that writes the drafts",
      agent_desc: "GigaMail has no built-in LLM: drafts are written by your agent (default: Claude Code, `claude -p`). Change it in agent.json.",
      consent_title: "Human verification (Hello / Touch ID)", desktop_title: "Desktop notifications",
      desktop_setup: "Enable buttons (UAC)",
      telegram_hint: "Configured from the terminal (the bot token never goes through this window): gigamail telegram setup, with --approve to approve from your phone (Hello).",
      login: "Login",
      no_mail: "No mail.", delete: "Delete",
      reply_to: "Reply to", attach_opts_title: "Click: open • Right-click: options",
      dock_back: "Dock back to console",
      use_draft: "USE THIS DRAFT", ignore: "DISMISS",
      open_in_window: "Open in window", ade_voice: "ADE voice",
      no_event_period: "No events in this period.",
      close_upper: "CLOSE", no_account: "No account",
      reply_subject_ph: "Reply subject...",
      cancel_upper: "CANCEL", new_reply_upper: "NEW REPLY",
      select_attach_auto: "Select files to attach automatically",
      add_note_ph: "Add note… or drag a file",
      reactivate: "Reactivate", done: "Done", completed: "Completed",
      folder_suggestion: "FOLDER SUGGESTION",
      yes_move: "YES, MOVE", no: "NO",
      no_personal_folder: "No personal folders.",
      no_folder_avail: "No folder available",
      config_folder_identity: "Configure folder identity",
      delete_folder: "Delete folder",
      unread: "Unread", sent_today: "Sent today",
      goto_account: "Go to account →", open_calendar: "Open calendar →",
      no_calendar: "No calendar configured",
      new_mail_badge: "NEW MAIL",
      identity_folder: "FOLDER IDENTITY",
      identity_folder_sub: "overrides account identity for this folder",
      who_here: "WHO YOU ARE IN THIS FOLDER", what_you_do: "WHAT YOU DO",
      tone: "TONE", folder_info: "FOLDER-SPECIFIC INFO",
      identity_account: "ACCOUNT IDENTITY", who_you_are: "WHO YOU ARE",
      tone_reply: "REPLY TONE",
      key_info: "KEY INFORMATION", key_info_sub: "(prices, hours, contacts...)",
      extract_url: "EXTRACT FROM URL", extract_url_sub: "(website, LinkedIn, product page...)",
      useful_files: "USEFUL FILES", useful_files_sub: "(.txt .md .csv — e.g. price list)",
      folder_btn: "📁 FOLDER", pick_folder: "Select folder",
      folder_word: "FOLDER", save_upper: "SAVE",
      recent_unread_5d: "Recent unread mail in the last 5 days",
      preview_identity: "EXTRACTED IDENTITY PREVIEW",
      preview_identity_sub: "Edit if needed, then confirm to apply to the fields.",
      info_key: "KEY INFO",
      who_ph: "Leave empty to use account identity",
      whatdo_ph: "E.g.: I reply to Idealista leads",
      tone_ph: "E.g.: Commercial, fast, direct",
      folder_info_ph: "Specific info for this folder...",
      lang_switch_title: "Lingua / Language",
      listen: "LISTEN", reply_upper: "REPLY", all_upper: "ALL",
      forward_upper: "FORWARD", summarize_upper: "SUMMARIZE", move_upper: "MOVE",
      not_spam_upper: "NOT SPAM", spam_upper: "SPAM", unread_upper: "UNREAD",
      delete_upper: "DELETE",
      press_summarize: "Press SUMMARIZE to generate the summary.",
      listen_cap: "Listen", reply_cap: "Reply", forward_cap: "Forward",
      summarize_cap: "Summarize", spam_cap: "Spam", delete_cap: "Delete",
      move_to_spam: "Move to spam?", delete_this_mail: "Delete this email?",
      add_account_btn: "+ Account", add_folder_btn: "+ Folder",
      recipients: "Recipients", subject_word: "Subject", format_word: "Format",
      load_csv: "Load CSV / Excel", preview: "Preview",
      to_word: "To", ai_instruction_word: "AI instruction",
      who_account_ph: "E.g.: Sales Office Project 20128 Milan",
      whatdo_account_ph: "E.g.: I reply to apartment inquiries",
      tone_account_ph: "E.g.: Professional, friendly, formal Italian",
      url_ph: "https://... or paste text with a URL",
      start_send: "Start sending", stop_send: "Stop sending",
      generate: "GENERATE",
      drag_image: "Drag image here", load_folder: "Load folder",
    },
  };

  // lingua corrente (default it)
  let currentLang = 'it';
  try { currentLang = localStorage.getItem('ade_lang') || 'it'; } catch (e) {}

  // traduzione di una chiave nella lingua attiva (fallback: italiano, poi chiave)
  function t(key) {
    if (!key) return '';
    const L = DICT[currentLang] || DICT.it;
    return L[key] || DICT.it[key] || key;
  }

  // applica la lingua a tutto il DOM (elementi con data-i18n*)
  function applyLang(lang) {
    if (lang) currentLang = lang;
    try { localStorage.setItem('ade_lang', currentLang); } catch (e) {}

    // testo interno
    document.querySelectorAll('[data-i18n]').forEach(el => {
      const key = el.getAttribute('data-i18n');
      const val = t(key);
      if (val) el.textContent = val;
    });
    // placeholder
    document.querySelectorAll('[data-i18n-ph]').forEach(el => {
      const key = el.getAttribute('data-i18n-ph');
      const val = t(key);
      if (val) el.setAttribute('placeholder', val);
    });
    // title (tooltip)
    document.querySelectorAll('[data-i18n-title]').forEach(el => {
      const key = el.getAttribute('data-i18n-title');
      const val = t(key);
      if (val) el.setAttribute('title', val);
    });
    // data-label (voci sidebar: tooltip via attributo data-label)
    document.querySelectorAll('[data-i18n-label]').forEach(el => {
      const key = el.getAttribute('data-i18n-label');
      const val = t(key);
      if (val) el.setAttribute('data-label', val);
    });
    // attributo lang sul documento + bottone lingua (sigla attiva)
    document.documentElement.setAttribute('lang', currentLang);
    const flag = document.getElementById('langSwitch');
    if (flag) flag.textContent = currentLang === 'it' ? 'IT' : 'EN';
  }

  function toggleLang() {
    applyLang(currentLang === 'it' ? 'en' : 'it');
    // refresh viste dinamiche (liste/card generate da JS) se le funzioni esistono
    try {
      if (typeof window.refreshCurrentFolder === 'function') window.refreshCurrentFolder();
      if (typeof window.loadAccounts === 'function') window.loadAccounts();
    } catch (e) {}
  }

  // espone API globale
  window.i18n = { t, applyLang, toggleLang, get lang() { return currentLang; } };

  // applica al caricamento
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => applyLang());
  } else {
    applyLang();
  }
})();
