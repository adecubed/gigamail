# Changelog

## Unreleased

- **No Windows Hello for a click in the console.** Deleting a mail or a
  folder, moving a mail, marking spam or not spam, and editing the
  calendar from the console no longer open the Windows Hello / Touch ID
  prompt: a prompt per click, for a person sorting their own inbox, made
  the console unusable. Deleting asks "are you sure?" in the console
  itself. The prompt stays where it protects something: sending mail
  from the console and every approval the agent asks for. See
  SECURITY.md for the trade-off.
- **Why Windows Hello is missing, said out loud.** On a PC where the
  prompt never appeared, the console and the CLI only said "no backend".
  Now the cause is named: the WinRT package missing from that Python,
  Hello not set up for that Windows user, disabled by policy, or busy.
  It shows in the console's AI card, in the refusal message, and in the
  new `gigamail approvals check`, which also opens one test prompt and
  reports its outcome. A refused verification now says why in the
  console too (cancelled, not configured, attempts exhausted).

- **One confirmation per appointment.** When a client accepted a time
  for a video call, three paths each drafted a reply to that same mail
  within minutes: the confirmation the watcher drafts at once (and it
  said "at our office"), the mail with the Zoom link, and a reply asked
  from Telegram. Three different texts meant three approval requests, and
  two of them went out. Now the mail with the link is the confirmation
  for a video call; the confirmation drafted at once says "by video call"
  when the thread is one and Zoom is not connected; a reply asked from
  Telegram or the desktop while another reply to that mail is waiting
  tells you which request to approve or edit instead of drafting a second
  one; the agent's `reply_mail` gets that pending request back instead of
  a new one; and a rule skips a mail another path has already answered
  (reason `already-answered`). A rejected or expired draft frees the
  mail again.

## v0.5.0 — 2026-10-07

- **A signature per account.** Each account can have a plain-text
  signature, set in the console (account identity, "Signature" field) or
  with `gigamail identity signature --set "..."`. It goes at the bottom of
  every mail the account sends: mail and replies written by the agent
  through MCP, drafts from the watcher's rules, replies asked from
  Telegram, follow-ups after an appointment, video-call links and mail
  composed in the console. It is added when the approval request is
  built, so the preview you approve already ends with it and the mail
  that leaves is exactly that text; changing the signature later does not
  touch requests already waiting. It is never added twice, and no agent
  tool can change it. Empty by default: nothing changes until you set one.
- **The installed app is signed too, not only the installer.** Releases
  now carry a code signing certificate on `GigaMail.exe` and on the
  uninstaller as well as on the installer, so Windows names the publisher
  for the app itself and not just for the setup. CI still builds and tests
  the app; `scripts/sign-release.ps1` takes those same files, signs them on
  the maintainer's PC and packs the installer there. Builds made anywhere
  else stay unsigned, as before.
- **An edited follow-up is rewritten on the next tick.** Asking from the
  desktop to change a follow-up after an appointment could leave it
  waiting one extra watcher cycle: on Windows the watcher's clock could
  read the edit as due a microsecond in the future.

## v0.4.1 — 2026-10-06

- **The console replaces an outdated backend by itself.** The backend
  stays running when the window closes, so the next start is instant;
  after an update the new console kept talking to the old backend, and
  features added on both sides stayed invisible until the process was
  killed by hand. `/health` now says which process answers and whether
  its code changed on disk since it started; a console that finds a
  backend older than itself, of another version or with changed code
  stops it and starts a new one before opening the window.
- **Console: view several accounts as one.** Drag an account tile onto
  another and they become one tile: counters added up, and one mail list
  with the mail of both, mixed by date, each mail tagged with its account.
  Opening, replying, deleting or moving a mail uses the account it belongs
  to, so a reply leaves from the right address. "Split" on the tile brings
  the accounts back. It works with three or more accounts and across
  providers. It is a view: credentials, identity, rules and archive stay
  per account, and the agent, the rules and the watcher keep seeing
  separate accounts. In this first version the standard folders (inbox,
  sent, drafts, spam, trash) are merged; search and personal folders
  follow the account of the mail last opened.
- **Approval notifications name the mail.** On Telegram and in the
  desktop toast, every approval now carries a line with the subject of
  the mail it is about (the one being replied to, or the new mail's own
  subject), unless the text already quotes it. A reply drafted from an
  instruction used to say only "Reply to Anna. Approve?", and the toast
  for a reply asked by the agent showed a raw `replying_to={...}`
  summary; it now shows the subject and the recipient.
- **A confirmation sent from the MCP server reaches the calendar, or you
  hear that it did not.** With the `appointments` extension on, a mail
  sent through `send_mail` or `reply_mail` is read by the headless agent
  to update the calendar. The MCP server runs inside the AI client
  (Claude Desktop, Claude Code), and from there `claude -p` can fail to
  start ("Not logged in"); the failed read looked like a mail with no
  appointment, so a confirmed appointment never reached the calendar and
  left no trace in the audit log. Now the failure is written to the audit
  log (`appointment` / `read_failed`, with the reason) and the mail is
  queued: the watcher, which runs on its own, reads it again and updates
  the calendar. If no watcher is running, or it still cannot read the
  mail after five tries, you get a Telegram and desktop notice that the
  mail was sent and the calendar was not updated. A confirmation or
  cancellation the calendar refuses now gets the same notice.
- **A client's reply the agent cannot read is read again.** The watcher
  reads clients' replies to update the calendar. When the agent failed
  on one, the reply counted as one without appointments: it was never
  read again, and the Telegram notice with the client's text said
  nothing about the calendar. Now the failure goes to the audit log
  (`read_failed`) and the reply is retried on the next ticks, up to five
  times. The first notice says the reply could not be read for the
  calendar and will be retried; if every try fails, a second notice says
  to update the calendar by hand.
- **Client replies reach the desktop too.** The "the client replied"
  alert went to Telegram only. It now also arrives as a desktop
  notification with a Reply button: the window that opens asks what to
  answer, and the watcher drafts it for approval. Edit from the desktop
  on such a draft rewrites it (it used to fail).
- **One free time named by the client gets its confirmation drafted.**
  When a client on a followed thread names one precise time and it is
  free in the calendar — a time we offered or a new one — the
  confirmation is drafted at once and waits for approval, instead of
  waiting for you to ask for it. Several times, a busy slot or an
  unreadable calendar still go to you.
- **Mail text goes to OpenAI only if you ask for it.** The search memory
  used OpenAI embeddings whenever `OPENAI_API_KEY` was in the server's
  environment, and MCP clients such as Claude Code pass their whole
  environment to the server: a key set for something else was enough to
  send mail text to OpenAI. Now OpenAI needs `GIGAMAIL_EMBEDDINGS=openai`
  as well. By default the memory uses a local Ollama if one is running,
  otherwise plain text search; `GIGAMAIL_EMBEDDINGS=off` turns
  embeddings off. If you relied on OpenAI embeddings, set the variable:
  without it, threads indexed by OpenAI are skipped by semantic search
  until they are indexed again.
- **GigaMail is a Claude Code plugin.** `claude plugin marketplace add
  adecubed/gigamail` and `claude plugin install gigamail@gigamail`
  register the `gigamail` MCP server and add the `gigamail` skill, the
  same one the Codex plugin ships, which teaches the agent the approval
  gate. The skill no longer speaks to Codex only: its setup and
  troubleshooting cover both clients. The server still comes from
  `pip install "gigamail[all]"`.
- **The Windows installer is code-signed.** From this release
  `GigaMail-Setup-X.Y.Z.exe` carries an Authenticode signature (Certum
  Open Source Code Signing, issued to the maintainer by name), so Windows
  shows a named publisher instead of "Unknown publisher". SmartScreen
  may still warn on the first downloads until the certificate builds a
  reputation. The release flow changed to make this possible: a `vX.Y.Z`
  tag builds the installer into a draft Release, `scripts/sign-release.ps1`
  signs it on the maintainer's machine, rewrites `sha512` and `size` in
  `latest.yml` and publishes; PyPI follows on publish. The `.blockmap` is
  no longer attached, so auto-update downloads the full installer.
- **Linux can approve, with a local PIN typed in a terminal.** Without
  Windows Hello or Touch ID nothing could approve a send or a deletion
  except Telegram, which made the weakest channel the only one. Now
  `gigamail approvals pin` sets a PIN (scrypt hash, 3 wrong attempts lock
  it for 15 minutes; changing or removing it needs the current one), and
  `gigamail approvals approve` asks for it, only in an interactive
  terminal: an agent running the command from a script gets no prompt.
  Weaker than Hello, and SECURITY.md says so. Windows and macOS are
  unchanged.
- **The approval channels are ranked in the docs.** Hello / Touch ID
  first, the Linux PIN second, Telegram last, stated as a convenience
  rather than the normal path. Telegram itself is unchanged.
- **After an appointment GigaMail asks how it went, and remembers.** One
  hour after a confirmed appointment starts it asks: showed up, didn't
  show up, postponed. The question arrives on Telegram and as a desktop
  notification whose buttons answer it (the window that opens takes your
  notes); `gigamail debrief` lists the ones still unanswered. Telegram is
  not required. The answer, and the couple of lines you add, go into
  that client's notes (the sender profile `sender_history` returns),
  dated, one line per meeting. Draft replies to that client read those
  notes from then on.
- **Automatic follow-up seven days after the meeting.** When the client
  showed up, a week later at 10:00 on a weekday GigaMail drafts a
  follow-up from your notes, in the same conversation, and sends it for
  approval like every other draft (Approve / Reject / Edit, on Telegram
  or from the desktop notification: Edit rewrites it with your note).
  It is skipped when you have already written to each other since the
  meeting, or when a new appointment is in progress. Delay and wait time:
  `GIGAMAIL_FOLLOWUP_DAYS` (7), `GIGAMAIL_DEBRIEF_DELAY_MINUTES` (60).
- **A conversation's own appointment no longer blocks its slot.** The
  client picked 17:00, GigaMail put it in the calendar, and the draft
  written a minute later found 17:00 "busy" and turned the client down.
  The thread's confirmed event is now left out of the free-slot search,
  and the prompt says the appointment is already set.
- **The IMAP server certificate is verified.** Until now the IMAP client
  connected with certificate checks switched off: on a hostile network
  (a public Wi-Fi) whoever sat in the middle could receive the account
  password. SMTP already verified. Now IMAP verifies too; a server with a
  self-signed certificate is accepted only for the account that declares
  it, with `gigamail accounts tls <id> --insecure`, which asks for Windows
  Hello / Touch ID (`--verify` turns checks back on). A rejected
  certificate is not retried, so the password is not sent again, and the
  error says which command to run.
- **`gigamail check`: onboarding verified end to end on a real account.**
  Until now "verified" stopped at "the agent sees the tools". The command
  searches the mailbox, prepares a mail to the account's own address,
  shows that it stays held, waits for a human to approve it (Windows
  Hello / Touch ID from `gigamail approvals approve`, or the console),
  sends it and finds it again. Same steps on Microsoft Graph and on IMAP;
  one mail, to yourself, nothing else.
- **The same path runs in CI on a real IMAP/SMTP server.** A new job
  starts GreenMail (jar pinned by SHA-256) and runs
  `tests/test_e2e_imap.py`: search, a reply held until approved,
  approval, the reply arriving in the other mailbox, the approval refused
  when reused.
- **`add_imap_account` accepts `insecure_tls`** for an SMTP server with a
  self-signed certificate: an explicit opt-in, for that account only.
- **A half-finished install no longer crashes `extensions install`.** A
  pip upgrade interrupted while `gigamail.exe` was in use left the venv
  without package metadata; the command now says what happened and how
  to fix it.

## v0.4.0 — 2026-09-30

- **The package is called gigamail.** The internal name `ade_mail_agent`
  showed up in tracebacks, in the commands given by error messages
  (`CLI: ade-mail-agent login`) and in every `python -m`. The package is
  now `gigamail` (`python -m gigamail.server`,
  `from gigamail.core import ...`), and the CLI help and the errors say
  `gigamail`. The old name stays as an alias: `ade_mail_agent.X` is the
  same module as `gigamail.X`, not a copy, and
  `python -m ade_mail_agent.cli` still works. This is why existing MCP
  configurations do not break, and neither does the gigamail:// protocol
  registered in HKLM under the old name, which is still recognised:
  notifications keep their buttons. The `ade-mail-agent` commands and the
  `%APPDATA%\ADE` data folder stay too.

- **The trade moves out of the core.** Whoever installs gigamail no
  longer carries along the agency it was born in. The flat types
  (two-room flat, three-room flat...) and the unit codes (`A.9.2`) that
  choose the attachments have become the `extras/real_estate` extension,
  a separate package that is installed with pip and switched on with
  `gigamail extensions enable real_estate`. The core offers the hooks
  (`core/extensions.py`): a constraint in the draft prompt, a check on
  the draft with an automatic rewrite before stopping, the codes cited in
  the text. Without extensions, attachments follow the rule's list.
- **Extensions are installed in the data folder.**
  `gigamail extensions install real_estate` puts them in
  `%APPDATA%\ADE\extensions` (`~/.ade/extensions`), not in the
  application's Python: the desktop app replaces that at every update,
  and an extension installed there disappeared. No administrator
  privileges, no git: the extension comes from the archive of the
  installed version's tag, so core and extension come from the same
  commit. The folder is appended at the end of `sys.path` (it cannot
  shadow a core module) and its `.pth` files are not executed. Installing
  asks for Windows Hello / Touch ID, as switching on does.
- **Appointments are off by default.** Before, every sent mail went
  through the agent in search of an appointment, and threads were
  followed to forward the replies to Telegram, for everyone. Now they are
  switched on with `gigamail extensions enable appointments`. Those who
  already used them (`.appointments.db` exists) find them switched on
  after the update: the migration happens only once.
- **An extension that is switched on but fails to load does not go
  unnoticed.** Automatic drafts stop as they do when the agent does not
  respond: three attempts, then the alert to the human. No draft goes out
  believed verified without being so. Switching on an extension asks for
  Windows Hello / Touch ID, like creating a rule: it changes what the
  watcher does on its own.
- **The anti-injection guard no longer knows the owner's name.** "Non
  avvisare <nome>" ("do not alert <name>") was recognised only for a name
  written in the code; the generic Italian words remain (utente,
  titolare, proprietario, umano, nessuno: user, account holder, owner,
  human, nobody).

- **GigaMail has its own archive: every mail, in full, forever.** Before,
  it kept nothing of its own and only read the server. But the server is
  not an archive: Outlook, configured as it almost always is, downloads
  the mail and deletes it from the server after a couple of weeks. On
  28/09 a bill that arrived in January existed only in the Outlook file,
  and GigaMail's search answered "no results" with complete confidence.
  Now `core/archivio.py` saves every message as it arrived, compressed
  MIME with the attachments, from every mailbox and every folder except
  drafts, with a full-text index on subject, sender, recipients, complete
  text and attachment names. Words are searched by prefix, so "casaesempio"
  finds info@casaesempioimmobiliare.example, and without accents. The same mail
  seen from the server and from Outlook, or moved to another folder,
  remains a single row thanks to the Message-ID.
- **Continuous sync.** On every pass the watcher brings into the archive
  what has arrived on the servers (IMAP by last UID and UIDVALIDITY,
  Graph from the most recent), with a cap per pass so that a first load
  of thousands of mails does not hold up the rules.
  `gigamail archive sync` does the first load in one go.
- **Outlook's history is imported on its own, once.** On the first pass
  over an account the watcher launches, in a separate process, the import
  of everything Outlook keeps on the PC for that address: it is the
  default, not an option to discover. Outlook does not expose the MIME,
  so the message is rebuilt from the original internet headers, the body
  and the attachments; if the same mail is still on the server, the
  server's copy wins. After that, GigaMail asks Outlook for nothing more.
  Three attempts at most, then it stops.
- **Search and reading go through the archive.** `search_mail` returns
  the archive's results first (id `arch-...`), which `read_message` and
  `read_attachment` read even when the server no longer has the mail. A
  server id that the server can no longer find is looked up in the
  archive before returning an error. If the server does not answer at
  all, search keeps working with the archive alone.
- **IMAP search with accents did not work.** The UTF-8 attempt was
  written without the word CHARSET and the server always rejected it:
  only the ASCII search was left, and that does not find "proprieta'".

- **The draft no longer copies old replies, and if it gets it wrong it
  corrects itself.** The flat-type constraint was not enough: sent
  replies still went into the prompt in full, together with the
  "suggested template" of the previous reply, and with those in front of
  it the agent copied instead of reading the mail. And when it got it
  wrong, the draft was simply discarded: in semi mode the human received
  an alert instead of a reply to approve. Now the automatic draft
  receives from the observer ONLY the learned style, words and length
  (`includi_esempi=False`), with no replies or templates. And if it
  proposes flats of another type, the watcher has it rewritten straight
  away with a concrete correction: what it proposed, what should have
  been proposed, where to take it from. It stops and alerts the human
  only if it gets it wrong on the second pass as well.

- **On Telegram the draft can be read in full.** The notification cut the
  draft at 400 characters: a reply with four flats, floor areas and
  prices stopped at the second line, and the rest of what was being
  approved existed only in the console. Now the draft goes in whole
  (`GIGAMAIL_NOTIFY_BODY_CHARS`, 3000 by default, with a visible mark if
  it is ever cut). And the channel no longer truncates silently past
  Telegram's limit: a long text is split into several messages, cutting
  at line breaks and never inside an HTML entity, with the approval
  buttons on the last piece, below the end of the text.

- **The draft answers the question in THIS mail, not the one before.** On
  27 September a client wrote about a two-room flat and was offered three
  three-room flats from 365,000 euros up, floor plans included. The
  attachments were correct, they followed the text: it was the text that
  answered the wrong question. The cause lies in the prompt, which
  receives examples of the latest sent replies and a "suggested template"
  chosen by subject similarity. Portal alerts have almost identical
  subjects, only the flat type changes, so the template was always the
  latest reply about three-room flats and the agent copied it. Now
  `core/tipologie.py` reads the requested flat type from the listing
  title, which the portal puts in the subject, and puts it in the prompt
  as a constraint; past examples are declared valid for tone and never
  for content. Downstream, the watcher checks the draft: if it lists
  flats and none is of the requested type, it skips it and leaves it to
  the human instead of sending it. A reply for the wrong flat type is not
  a slip of form, it is a reply to another client.

- **The approved attachment is the one that goes out, byte for byte.**
  The request pinned the file path, not the content: between approval and
  sending it was enough to replace the file on disk (Loopjacking) and a
  different document went out with the same name, under a valid approval.
  Now `core/attachments.resolve()` reads the bytes when it creates the
  request and pins their SHA-256 and size in the approved arguments; the
  preview shows size and fingerprint (`sha256`, 12 characters) and
  `payload()` recomputes the hash at send time. If it does not match, or
  if the request is old and has none, it raises `AttachmentChanged` and
  nothing goes out: the request has to be recreated.

- **Recipients, account and folder stay the approved ones.** SMTP no
  longer includes the Bcc header in the delivered message. Graph replies
  without attachments respect explicit To/CC/Bcc; IMAP replies use the
  original folder. MCP requests pin the mail account or the calendar
  before approval; old ones with no pinned destination have to be
  recreated. The Microsoft context is isolated between concurrent
  requests.
- **Direct actions from the console require system verification.**
  Sending, deleting and moving mail, and calendar writes, ask for Windows
  Hello / Touch ID even with a valid token. Cancellation, a provider
  error and dry-run keep the draft; local audit or address-book errors
  after a successful send no longer make it look failed. The popup passes
  account and attachments to the API correctly.
- **IMAP does not delete the original if the copy to the trash fails.**
  The given folder is respected, UID MOVE is preferred and UID EXPUNGE is
  used when available; the fallback checks the other messages already
  flagged for deletion.
- **The watcher also fetches mail beyond the first page.** It keeps the
  approved folder, CC and attachments, retains failed outcomes and
  protects mail with a pending reply from archiving even if the rule is
  suspended. Appointment updates follow the order of the messages: read
  or calendar errors stay to be retried, and a failed cancellation is not
  announced as successful.

- **Attachments follow the mail, and an empty promise does not go out.**
  The idealista rule had a fixed set of three floor plans: those always
  went out, whatever the client asked for. On 19 and 23 September it cost
  dearly, twice. Someone who wrote about a four-room flat received the
  floor plans of three first-floor three-room flats; the next mail, the
  one that listed the flats actually requested, said "please find the
  floor plans attached" and went out without a single file. Now
  `core/attachments.py` reads the flat codes from the text (`A.9.2`,
  `B.7.4`) and those decide what is attached; the rule's list stays as a
  fallback for mails that name no flat. On top of that, a fail-closed
  barrier in all three send paths: if the text announces an attachment
  and not even one has been resolved, the watcher skips the draft and
  leaves it to the human, and `send_mail` / `reply_mail` return an error
  without even creating the approval request. A mail that contradicts
  itself in front of the client is worse than a mail not sent.

- **The appointment carries the client's name, not ours.** Our
  confirmation signed "Ufficio Vendite" gave the event its title: the
  agent took whoever had signed. Now a name that is ours (account,
  identity, office labels) never counts as a person, the display name of
  whoever replies takes precedence, and when the name arrives after the
  event only its title is updated.
- **You can reply to the client from Telegram.** The "the client has
  replied" alert arrived on Telegram and ended there: to reply you had to
  go back to the PC. Now there is a Reply button under the alert, and you
  can also reply directly to the message. What you write ("ok, that's
  fine") is an instruction: the agent writes the draft with identity,
  free slots and the anti-injection guard, and the mail arrives for
  approval with the usual buttons, Edit included. Nothing goes out
  without a yes.

- **A repeated confirmation no longer rewrites the appointment.** A
  client's "thanks, see you tomorrow" was read as a new confirmation: the
  event was updated with the email address instead of the name in the
  title and with an empty location, Zoom link included. Now a
  confirmation with the same time does not touch the calendar, a
  reschedule changes only the times (and the location only if a new one
  arrives), and the title of a new appointment uses the sender's name
  instead of their address.

- **The personal Zoom link is enough, with no app to create.** Connecting
  Zoom required a Server-to-Server app on the marketplace, five minutes
  in the browser that not everyone wants to spend. Now you paste the link
  of your personal meeting room into the console's Zoom tab: GigaMail
  puts it in the confirmation mail of every video call, always after
  approval, and writes it into the calendar event. A new time does not
  generate a second mail, because the link is always the same. With the
  app connected the previous behaviour stays, a different link for each
  appointment.

- **A decided request removes its notification from the PC.** Approved or
  rejected on Telegram, from the console or from the CLI, the toast
  stayed in the notification centre and invited you to press Approve on a
  request already closed. Now approval, rejection, revocation and
  execution withdraw it.
- **A plain-text mail is shown with its line breaks.** In the console, an
  address in angle brackets in the quoted text (`<info@vendite.example>`)
  was enough to treat the whole mail as HTML: line breaks disappeared and
  reply, quote and legal notice became a single block. Now what counts is
  the type declared by the server and, if that is missing, a real HTML
  tag.

- **The console calendar really shows the days it asks for.** The console
  requested `/calendar?days=60`, the backend read only `days_ahead` and
  always answered with 7 days: an appointment ten days away, already in
  the calendar, was missing from the console. Now `days` counts the same
  as `days_ahead`.

- **SECURITY.md no longer passes Telegram off as Windows Hello.**
  It said approving from Telegram was of the same nature as Hello. It is
  not: Hello is asked for at every approval, on the device; on Telegram one
  tap is enough in any client signed into the account, including Telegram
  Desktop open on the PC the agent runs on. The page now says so, says
  what holds today (Telegram approval is opt-in; without `--approve` it
  stays notifications only) and what is planned: approval from the phone
  only, inside a Mini App that asks for its biometrics. Pointed out on
  Reddit by **u/Bitter-Connection506**. Thank you.

## v0.3.4 — 2026-09-15

- **Mail from idealista ends up in the idealista folder on its own.**
  Nobody was moving it: the folder had stopped at 30 August and the inbox
  held 138 of those mails. The watcher has a new phase that moves into
  the configured folder the mails from a domain and its subdomains that
  arrived after activation. A mail is moved only when no rule needs to
  find it in the inbox any more (sent, discarded, rejected or expired):
  IMAP changes the id of a moved mail, and a draft awaiting approval or
  to be redone would not find it again. A failed draft stays where it is,
  so that a human sees it. A failed move is retried at most three times.

- **The console's Move button works, and the window closes.** The console
  sent the folder in the request body, the backend wanted it in the
  query: every click ended in a 422 and the window stayed open. On top of
  that, the X at the top was wired to nothing. Now the backend accepts
  both forms, the X closes, the proposed folder is no longer the one the
  mail is already in, a failure from the mail server is shown on screen
  and validation errors no longer read as "[object Object]".

- **"Ask your mail" finds mail even without the agent.** With the agent
  disconnected the window showed "(no answer)", even when the mail being
  looked for was in another mailbox. Now, if the agent does not respond,
  the question becomes a keyword search across all mailboxes, with the
  mails found clickable and the reason written in the answer. A backend
  error is shown on screen with its message.

- **Zoom connected: a confirmed video call gets its link straight away.**
  Before, the user created the link by hand and sent it with another
  round of requests. Now a mail that talks about a video call marks the
  thread; when the client confirms the time GigaMail creates the Zoom
  meeting (waiting room on), puts the link in the event and prepares the
  mail with the link, which goes out only after approval and is executed
  by the watcher. A new time moves the same meeting without another mail,
  a cancellation deletes it. It is connected from the console (Add
  account > Zoom) with the three codes of a Server-to-Server OAuth app,
  checked with Zoom straight away: rejected credentials are not kept, and
  the secret stays encrypted and never goes back to the page. From the
  terminal, `gigamail zoom setup|test|remove` remain. New two-phase MCP
  tool `create_zoom_meeting`. Without Zoom connected the alert says so
  and nothing is created.
- **Every outgoing mail puts the thread on watch.** Only replies were
  followed: a client replying to a new mail, with price list and floor
  plans, generated no alerts. The addresses of our own accounts stay out
  (for company domains the whole domain, for public providers the exact
  address).

- **The time the client picks goes into the calendar, and the alert shows
  the reply.** The alert said who had replied and the subject: the news
  that a mail exists, not what it says. Now it carries only the name and
  the text of the reply, without the quote, plus a line on what happened
  in the calendar. When the client gives a single precise date and a
  single precise time and the calendar is free, the appointment is
  inserted straight away. If the time is taken, if more than one is given
  or if the calendar cannot be read, nothing is inserted and the alert
  says so.

- **A disconnected agent no longer writes drafts.** Claude Code without a
  login exits with code 1 and prints "Not logged in · Please run /login"
  on stdout. `agent_bridge.run` discarded the error when the output was
  not empty, and returned that sentence as the answer: a draft with that
  text would have arrived for approval as a mail to a client, and reading
  appointments failed without saying why. Now an exit with an error is
  always `AgentUnavailable`, and so is a short login message even with
  exit 0.

- **A proposal no longer invents an appointment, and the client's reply
  reaches a human.** Found live, on a client who had picked Monday
  morning without anyone seeing it:
  - the phase that rereads open threads judged replies by the subject
    alone, because the IMAP list does not carry the text. Now the text is
    downloaded only for messages in open threads, and each one is looked
    at only once;
  - someone replying from their own mailbox instead of from the portal
    generated no alert at all. Replies sent by a rule put the thread on
    watch, and every new reply arrives on Telegram with the time that was
    read and the text without our quote;
  - a proposal became a `[da confermare]` block on the first of the
    offered times, reminder included, even for people who never replied.
    Now only the confirmation goes into the calendar;
  - the slot window was fixed from 09:30. Now it is read from the
    settings (`slot_work_start`, `slot_work_end`, `slot_patrono`,
    `slot_skip_holidays`), Italian public holidays are excluded and the
    draft always invites the client to suggest an alternative;
  - reading a mail via IMAP marked it as read (`RFC822` instead of
    `BODY.PEEK[]`): the watcher would have removed from the unread mail
    precisely the replies it has to report.

## v0.3.3 — 2026-09-11

- **Mail and calendar talk to each other, both ways.** They were two
  separate worlds: `calendar_router` was called only by the console, the
  HTTP API and the CLI, never by the mail path. You could propose an
  appointment in a mail, send it, and find no trace of it in the calendar
  — it really happened, and you don't find out until the client turns up
  (or until we turn up). On the way out, `mail_router.send_message` now
  passes every sent mail, whichever route it comes by (MCP, watcher
  rules, console), to the new `core/appointments.py`: a proposal becomes
  a `[da confermare]` block, the client's confirmation promotes it, a
  cancellation removes it. On the way in, the watcher has a new phase
  that rereads ONLY the threads with an open appointment. What reads the
  message is the user's agent, not a regex on dates, but first there is a
  zero-cost filter: a mail with no times and no appointment words does
  not even start the process. Sending never waits for the calendar
  (fire-and-forget thread) and every step is fail-closed: agent missing,
  unreadable JSON, date missing, in the past or more than a year ahead,
  event created without an id => the calendar is not touched and a line
  is left in the log. A mail that gives orders to the assistant does not
  get into the prompt.
- **The agent sees the calendar BEFORE proposing a time.** The draft
  prompt said "do not use tools" and did not carry the calendar: the
  agent proposed dates at random and the user ended up with two things in
  the same slot. Now `build_draft_prompt` includes the free slots
  computed by `availability.find_free_slots` (not by the agent: it gets
  weekends, time zones and overlaps wrong) and forbids proposing others.
  If the calendar does not respond, the section says so and forbids
  precise times. `GIGAMAIL_SLOT_DAYS` moves the horizon,
  `GIGAMAIL_SLOTS_SABATO=1` is for those who also see clients on
  Saturdays.
- **The cc of `reply_mail` was never sent.** The tool accepted it, it
  ended up in the args and appeared in the preview the human approved,
  but `execute_fn` did not pass it to `reply_message`: whoever approved
  saw the promised copy and the cc recipient received nothing, with no
  error anywhere. One line, plus the regression test to guard it.

- **A Codex plugin.** `codex plugin marketplace add adecubed/gigamail`,
  then `codex plugin add gigamail@gigamail`, installs GigaMail in Codex
  (CLI and desktop app). The manifest that already sat in `.codex-plugin/`
  now points to a skill (`skills/gigamail/`: the approval gate explained to
  the agent, the same policy as the ClawHub skill, with Codex's own
  commands) and to `.mcp.json`, which registers the `gigamail` server and
  forwards `APPDATA`, `GIGAMAIL_ROOT` and `ADE_ROOT` through `env_vars`, so
  the server sees the console's data directory without `codex mcp add`. A
  one-plugin marketplace (`.agents/plugins/marketplace.json`) makes the
  repository installable as is. Verified with codex-cli 0.148: skill
  loaded, 28 tools, `list_accounts` on the real accounts (INTEGRATIONS.md).
  A test keeps manifest, skill, marketplace and tool names coherent with
  the server.
- The plugin manifest's privacy link points to gigamail.ai/privacy.html
  (it pointed to SECURITY.md) and its category is Communication, where
  Codex lists the other mail plugins.

- **The draft prompt reached the agent truncated.** npm installs `claude`
  and `codex` as `.cmd` wrappers, so CreateProcess launches them through
  cmd.exe, which cuts the command line at the first line break. The
  process started, the agent received the first line and nothing else:
  identity, documents and mail body never left `agent_bridge`. The draft
  came back with "I can't see the email to reply to" and looked like a
  model problem. `run()` already sent the prompt on stdin when it was too
  long; now it also does so when it contains a line break, that is,
  always.

- **The draft follows the language of the sender.** It was hardwired to
  Italian inside the prompt, in two places: to a client writing in
  English the agent replied in Italian, and that is a mistake that shows
  at once. Now the reply comes out in the language of the mail received,
  and text composed from scratch follows the language of the instruction.
  The marker for what is missing has its own form per language:
  `[DA COMPLETARE]` or `[TO BE COMPLETED]`.

- **The guard against mails that give orders to the assistant.** The body
  of a mail is data, not instruction, but it ended up in the prompt next
  to the request to write a draft. `injection_guard` runs BEFORE
  generation: if it triggers, no draft is written and no attachment is
  proposed, and the mail goes back to the user with the reasons and the
  offending passage. It is deterministic and local — patterns, no model —
  so the text it analyses cannot manipulate it. Declared limit: it
  recognises known phrasings; it is the first layer, not the last. It
  covers the two paths by which a received mail gets into the prompt: the
  console's `smart_draft` and the rules' drafter. The second is the more
  exposed, because a rule in auto mode can also send on its own: there,
  the mail giving orders produces no draft, is not retried, and the human
  sees it with the reason for the block. Mentioning a password is not
  enough to trigger the check, it takes a verb asking for it: real mail
  talks about passwords and forwarding all the time, and a guard that
  blocks the notary gets switched off on day one. In English the first
  person and the imperative have the same form, so "I will send the file
  passwords separately" triggered the check: now it also looks at who
  comes before the verb. Reasons travel as codes and not as Italian
  sentences, because in an English console they showed up as they were
  inside the security alert.

- **Folder identity now actually reaches the draft.** It could be
  configured from the console and saved in the database, but nothing read
  it: `smart_draft` always took only the account identity, so the same
  mail got the same reply in Lead and in Clienti. Now the folder
  overrides the fields it has filled in, and its knowledge paths are
  added to the general ones.

- **Documents go into the draft, with the discipline that takes.**
  Knowledge files were chosen by name to propose attachments, but they
  were never read: the price was in the price list on the same disk and
  the draft still answered "we do not have this information".
  `read_relevant_excerpts` puts the content in the prompt under the label
  `DATI SPECIFICI DALLA DOCUMENTAZIONE`, declared reliable. The
  permission is narrow and applies to that block only: outside it, the
  draft neither asserts nor denies the existence of services, agreements
  or conditions that are not in the documents, promises no timings, and
  writes whatever is missing as `[DA COMPLETARE]`, literally. Without
  those lines the draft invented bank agreements that did not exist.

- **A mailbox in a file, for filming and for testing.** `demo_mailbox`
  serves mail from a JSON file instead of IMAP or Graph: no connection,
  no credentials, and what the agent 'sends' ends up in the file's sent
  mail. The console, the MCP server and the rules go through the same
  code as always. It is not a global mode and is not switched on by an
  environment variable: it exists only if someone creates an account of
  type `demo`, and the installer creates none. A demo account has no
  connected calendar, and the router now says so instead of falling back
  to Microsoft and asking for a login that does not exist.

- **The console shows when the guard stops a mail.** Without this,
  pressing GENERATE on a hostile mail left the field empty and looked
  like an application fault. Now a banner appears with what was
  recognised and the offending passage, and no attachment is proposed.

- **Dry run of the video scenes.** `demo_video/preflight_test.py` runs on
  the real pipeline with made-up data: no mailbox opened, data root
  redirected to a throwaway folder. Eleven checks across the four scenes,
  stable over three runs. `demo_video/allestisci.py --scena N` sets up
  the mailbox for a single scene and prints the shooting sheet, so each
  scene becomes a short video of its own. It also skips the first-run
  procedure: on a fresh data root the overlay covered the mailbox and the
  application looked stuck. `demo_video/registra.py` drives the real
  console via CDP and delivers the scene's mp4: the windows are captured
  from their renderers and composited, so only the application gets into
  the video and never the rest of the desktop of whoever is recording.
  Each scene leaves the script cues next to its mp4, and
  `demo_video/unisci.py` turns them into a single video with title cards
  and subtitles anchored to those cues: the length of a stretch changes
  with every take, so subtitles fixed on paper would drift off at the
  first retake.


- **Moving a mail now asks for approval.** `move_message` sat among the
  free writes because it destroys nothing and is undone by putting the
  message back where it was. Except that blast radius and cost of
  oversight are not the same axis: an agent that moves a mail into a
  folder the human does not look at has hidden it from them, without
  deleting anything and without going through any gate. It becomes
  two-phase, like sending and deleting. The preview shows sender, subject
  and — the thing that matters — source and destination folder with their
  readable names, not Graph's opaque id; `full_preview_text` and the
  toast summary have learnt those two fields, because with sender and
  subject present the destination was not printed anywhere on Telegram.
  Moves the human makes from the console go through
  `POST /mail/{id}/move` and stay immediate: nobody asks themselves for
  permission. Declared cost: automatically tidying many mails becomes
  impractical; the cap stays at 20 requests per tool per hour.
The Google side still needs an OAuth client from a Google Cloud project
before any of it can run — see [GOOGLE_SETUP.md](GOOGLE_SETUP.md).

- **The calendar has a router.** `list_events`, `find_free_slots`,
  `create_event` and `delete_event` used to call Microsoft Graph
  directly, from nine places across the MCP server, the console API and
  the agent bridge. That, not the missing client code, is why a second
  calendar could not exist. `calendar_router` now picks the backend and
  every caller goes through it.
- **Google Calendar as a backend.** Events come back in the Microsoft
  Graph shape, so `availability.py`, the free-slot computation and the
  console calendar window are untouched. The subtle part: Google returns
  RFC3339 with a `+02:00` offset, and `_parse_graph_dt` strips
  milliseconds and `Z` but not an offset — an aware datetime would have
  crashed `find_free_slots` against the naive ones. Times are converted
  to naive Europe/Rome at the boundary, and a test holds that line.
- **Connecting Google never moves your calendar.** With a Microsoft
  account present the calendar stays on Microsoft until the user says
  otherwise, from the console or `gigamail google calendar google`.
  Linking Drive must not silently relocate someone's appointments.
- **Google Drive, four tools.** `drive_list_files` and `drive_read_file`
  read (Docs, Sheets and Slides are exported to Office formats so they
  extract like any attachment); `drive_upload_file` and
  `drive_delete_file` need human approval out of band, like sending mail.
  Deleting moves the file to the Drive trash, never erases it.
- **Scope `drive.file`, on purpose.** GigaMail sees only the files it
  created itself. Full Drive access is a restricted scope and would drag
  every release through an annual paid security assessment. The tools say
  so in their own descriptions, so an agent that finds nothing knows why
  and stops retrying.
- **OAuth by loopback with PKCE, no Google libraries.** Google's device
  flow does not cover these scopes, so the desktop redirect is the only
  route; the flow is plain `requests`, like the rest of the HTTP here.
  Refresh tokens live in the encrypted account database (Fernet, DPAPI on
  Windows); access tokens stay in memory. A redirect whose `state` does
  not match is dropped without exchanging the code.
- **A revoked account says so.** `invalid_grant` on refresh surfaces as
  "reconnect", not as a network fault, so the agent stops retrying.
- **Three defects found by the first real setup**, each with a test. The
  browser asks the loopback port more than once: after the redirect it
  requests `/favicon.ico`, with no parameters, and recording that wiped
  the authorisation code — the login then died accusing a legitimate
  redirect of CSRF. The callback page said "connected" the moment the
  code arrived, before the token exchange that can still fail, sending
  the user to look for the problem in the wrong place. And Google's
  errors were hidden behind the HTTP status: a bare `403` cannot tell an
  API disabled on the project from a missing permission, so the body
  Google actually sends is now surfaced with the remedy.
- **Credentials come from the file Google hands you.** `gigamail google
  setup <client_secret_*.json>` validates and installs it; a "Web
  application" client is refused at that point rather than three browser
  screens later. Nobody has to retype an id and a secret that look
  identical to every other id and secret. And each source must supply
  **both** halves: an incomplete one is skipped, never topped up from the
  next, so an id and a secret can no longer arrive from different places
  and produce an `invalid_client` with nothing to go on.
- 28 tools, up from 24. `gigamail google setup|login|status|logout|
  calendar` in the CLI, a Google panel in the console, `/google/*` in the
  console API. 50 new tests.

## v0.3.2 — 2026-09-08

- **Codex CLI as a first-class agent.** The console detects `codex` next to
  `claude`, lets you pick the agent that writes the drafts (first-run guide
  and Automations), stores the choice as `{"agent": "codex"}` in
  `agent.json` and resolves the command at every start. Drafts run through
  `codex exec` in a read-only sandbox, with the final answer read from a
  file. The MCP registration snippet switches to `~/.codex/config.toml`
  (or `codex mcp add`) when Codex is selected. Both directions verified on
  Windows — see INTEGRATIONS.md, including the gate holding with Codex's
  own approvals bypassed.
- `.codex-plugin/plugin.json` follows the release version (it was still
  0.2.4 at 0.3.1); `sync-version.js` and a test keep it aligned.
- **Attachments open again from the console.** Clicking an attachment
  answered "HTTP 404" on every account: the console asked the backend for
  `GET /mail/{id}/attachment/{name}` and that route did not exist. It
  does now (bytes, content type from the provider or from the file name,
  proper `Content-Disposition`), with tests.
- **An old notification says it is old.** Pressing a desktop toast after
  its request has expired or been decided used to answer "request does
  not exist", which reads like a fault. It now says the notification is
  stale and lists what is actually waiting, if anything; and the window
  no longer dies with a traceback when there is no standard input.

## v0.3.1 — 2026-09-04

Small things noticed while recording the 0.3.0 demo.

- **Grey text meets WCAG AA.** Dates, captions, placeholders and every
  secondary label sat at 30-45% black on white (2.1-3.4:1, below the 4.5:1
  the AA level asks for). The floor is now 55% black (4.7:1), the
  `--text-secondary` token is 60%, and `--text-muted` — used but never
  defined — exists. A test scans the console sources so it cannot regress.
  Pointed out on r/UXDesign by **u/Mrmasseno**. Thank you.
- **A calmer look, same identity.** Card and list borders go from black at
  75% to a light grey; corners from 16/28px to 10/16px; shadows from heavy
  to barely there; six pixels of air between messages; the window buttons
  top-right match the pop-out button (flat tint, light border, soft
  shadow); the mail body sits in a rounded white card. The secondary
  windows lose a body shadow that had nowhere to go and smeared their
  bottom edge, and get thin scrollbars like the main window. Text never sits on a gradient any more: active chips, the
  selected message, title bars and the "New mail" button use a flat tint,
  and the pink-blue gradient stays only on the avatar, the logo and the
  microphone states. Every one of these came from r/UXDesign:
  **u/AbilityRadiant2342** (the list) and **u/el_paro** (text over
  gradients). Two tests keep the dark borders and the gradients from
  creeping back.
- **Dates and calendar follow the UI language.** Every date, time, month and
  weekday name was formatted with the Italian locale regardless of the
  language chosen; the calendar window title and its "+ Event" button were
  Italian too. Formatting now uses the locale of the active language
  (`it-IT`, `en-GB`, `zh-CN`) and month/day names come from `Intl`.
- **"From:" / "To:" in the mail detail** were hardcoded in Italian.
- **Dashboard no longer flashes "Loading…"** on every folder change: the
  last rendered dashboard stays on screen while the data refreshes.
- **Reply and new-mail windows are children of the main window**, so they
  cannot end up behind a maximized main window (they had to be fished out
  of the taskbar).
- **A 90-second demo video** of the console lives in `docs/demo/` and is
  linked from the README.
- `npm test` only runs `tests/*.test.js` (it used to pick up any `.js`
  under the console folder, including the embedded Python's own test files).

## v0.3.0 — 2026-09-04

The desktop console grows up. 0.2 shipped it as a beta next to the pip
package; 0.3 is about making it something a person can install and use
without reading the README.

- **Onboarding on first launch.** A fresh console no longer opens on an
  empty window: a guided setup inside the main window — same style as
  every other panel, no separate popups — connects a mailbox (Microsoft
  365 device flow or IMAP), fills the account identity and knowledge
  files, shows how to register GigaMail in the agent's MCP client and
  enables notification buttons. It is skippable, reopenable from
  Automations → AI (and from the dashboard while no account exists),
  and its "done" flag lives in the backend, so reinstalling the console
  does not bring it back. Italian, English and Chinese.

- **IMAP accounts are verified before they are saved.** The console
  sent a `provider` key the backend did not know and required hosts it
  did not have, so Gmail/Aruba/Libero saves failed with a 422 — and a
  wrong password was stored silently, to fail at the first sync.
  `POST /accounts/imap` now resolves the provider to its hosts (Outlook
  over IMAP included, SMTP 587 + STARTTLS), attempts a real IMAP login
  and answers 400 with a readable reason instead of writing the account.
  The first account becomes the active one.

- **IMAP-only installs load their accounts.** The console treated
  "connected" as "has a Microsoft token", so a console with only IMAP
  accounts never populated the account selector.

- **One way to render a mail, tested with hostile mail.** The HTML of a
  message went into an iframe by two different code paths (main window
  and mail window) with two different rules; now `mail_render.js` is the
  only one: structural sanitisation via DOMParser (scripts, frames,
  objects, forms, meta, base, links, every `on*` attribute, `javascript:`
  and `vbscript:` URLs, CSS `expression()`), an iframe sandbox with
  neither scripts nor popups, its own CSP, and link clicks that go to the
  system browser instead of navigating the frame. Seventeen known XSS
  payloads run through it in unit tests (jsdom) and in the real Electron
  (`npm run test:e2e`, Chrome DevTools Protocol), which also checks that
  the renderer has no Node, that the preload exposes no secrets, and —
  on a pristine profile — that onboarding opens by itself. The e2e runs
  in CI on Windows before every installer build.

- **The watcher is a package.** `watcher.py` had grown to 1,150 lines
  doing polling, rule matching, drafting, addressing, approvals,
  notifications, Telegram commands and execution in one file. It is
  now `ade_mail_agent/watcher/` with one module per responsibility
  (ingestion, drafting, addressing, approvals, notify, pipeline,
  execution, telegram, process_state, runner) behind the same facade:
  `from ade_mail_agent import watcher` and every public name still
  work, the CLI and the console did not change. The `except: pass`
  around the heartbeat and the Telegram trust warning now log through
  `logging` ("gigamail.watcher") instead of vanishing — a heartbeat
  that fails is exactly what makes the console launch a second watcher.

- **The console API is a package of routers.** `http_api.py` (1,200
  lines, 81 endpoints) is now `ade_mail_agent/http_api/` with one
  FastAPI router per domain — accounts, addresses, mail, calendar,
  mask, agent, approvals, rules/watch, notify/onboarding — behind the
  same `app`, the same paths and the same token middleware (kept in the
  facade so `importlib.reload` in tests still re-reads the token).
  `python -m ade_mail_agent.http_api` and the `gigamail-console-api`
  entry point are unchanged.

- **Mail list and detail leave renderer.js.** `renderer_mail.js` holds
  the list, the message detail with its actions and attachments, and the
  forward composer; the pure parts (`MailView`: list item, detail header,
  HTML→text) are unit-tested with hostile subjects, senders, addresses
  and attachment names. Two things fixed on the way: the forward path
  extracted text by assigning raw mail HTML to an element attached to
  the live document (an `onerror` would fire in the main window), now
  it parses into an inert `DOMParser` document; and the old
  `openMailWindow` built an unescaped HTML page for a `window.open`
  that main.js denies — dead code replaced by a delegation to the real
  mail window. renderer.js goes from 2,055 to 1,465 lines.

- **Composition leaves renderer.js too.** `renderer_compose.js` holds
  the reply modal, the new-mail panel, attachments and the recipient
  autocomplete; the pure parts (`ComposeView`: attachment chips,
  autocomplete items, suggested-attachment rows, address split/merge)
  are unit-tested with hostile names and addresses. renderer.js is now
  894 lines, down from 2,055 this morning.

- **Accounts and calendar leave renderer.js.** `renderer_accounts.js`
  (selector, IMAP modal, delete with context menu) and
  `renderer_calendar.js` (event list, quick popup, editor), with the
  pure parts (`AccountsView`, `CalendarView`) unit-tested with hostile
  names. The event quick popup was one of the hand-built overlays with
  its own palette and an undefined `--mono`; it now uses the console's
  `.overlay > .modal`. renderer.js is at 678 lines.

- **Every console module binds its own buttons.** `bindStaticEvents`
  was a 290-line list of every click handler in the main window; now
  mail, compose, calendar and accounts each have a `bind*Events()` and
  renderer.js keeps login, office and window navigation. The 52 bound
  ids are asserted identical before and after, and the e2e clicks
  through folder switching, the IMAP modal and the event editor.
  renderer.js: 466 lines (2,055 this morning).

- **Secondary windows closed too.** A second external review found what
  the first pass had left: the mail window put a plain-text body into
  `innerHTML` unescaped and, on "Forward", parsed the original HTML in an
  element attached to the live document; the calendar window rendered
  event ids and locations unescaped and put attendee addresses inside an
  inline `onclick` string with an `esc()` that did not cover the quote.
  All fixed (`esc()` before `<br>`, the shared inert `htmlToText`, data
  attributes instead of inline JS). `shell.openExternal` is now reachable
  only through one main-process function that accepts `http`, `https`
  and `mailto` — the main-window preload used to call it directly, the
  mail-window IPC forwarded anything — and every window gets the same
  popup/navigation hardening. The e2e opens the mail and calendar
  windows, injects hostile messages and events, and asserts nothing
  runs; it also asserts `openExternal('file:...')` is refused.

- **`webSecurity` back on everywhere.** Calendar, marketing and ask ran
  with `webSecurity: false`, which switches off the same-origin policy
  for the whole window (a page could read `file://` and call any host).
  Removed from all three; the backend already answers `file://` origins
  through CORS, so nothing needed it. `api.anthropic.com` is gone from
  every window's CSP. The e2e proves `fetch('file:///…')` is refused in
  the main, calendar, marketing and ask windows and that the calendar
  still reaches the backend.

- **The console shows only what the backend can do.** Marketing, voice,
  "Listen", "Summarize", the calendar TTS and the draft autosave all
  called endpoints that no longer exist and answered with 404s. The
  console now reads `/openapi.json` at start-up and every button
  declares the endpoint it needs (`data-requires="/path"`); a missing
  path hides the button, and it comes back by itself the day the backend
  offers it. The marketing window's direct, key-less call to the LLM
  provider is gone — that is the agent's job, through MCP.

- **Electron 44, electron-builder 26, better-sqlite3 13.** `npm audit`
  went from 1 critical + 9 high (Electron itself: context-isolation
  bypass and sandboxed-iframe escape; `tar`, `extract-zip` and
  electron-builder at build time) to zero. better-sqlite3 has prebuilt
  binaries for the Electron 44 ABI, so nothing is compiled on the
  machine. Building the console now needs Node 22 or newer (CI uses
  22); `npm test` runs `node --test` with the default pattern, which
  works on Node 20, 22 and 24 alike.

- **`ADE_CONSOLE_PORT` works end to end.** The main process knew the
  port; the renderers had `8002` written in 27 places across 17 files.
  Now every window receives the backend base URL from the main process
  (`additionalArguments` → preload → `window.GIGAMAIL_API`) and no
  renderer carries the port any more; the e2e runs on port 8012 in CI
  to prove it. `ade_mail_agent.__version__` comes from the package
  metadata (it had been stuck at 0.1.2) with a test against
  `pyproject.toml`, and `MAPPA_MCP.md` finally describes the
  out-of-band `request_id` flow instead of the old `confirm_token`.

- **A way back from a custom folder.** Inside a custom folder (say
  "idealista") the only route to the inbox was the sidebar icon, which
  does not read as "back", and the panel title kept saying "Inbox". Now
  the folder row starts with an "Inbox" chip, the active chip clicked
  again returns to the inbox, and the title follows the folder you are
  in (standard folders translated, custom ones by name).

- **The installed app is started in CI, not just installed.** The e2e
  runs on the development Electron with the backend from the venv; the
  installer was built, installed and uninstalled, but the exe a user
  gets was never launched. `npm run test:packaged` now starts the
  packaged app on a pristine profile, waits for the embedded Python
  backend (`/health` reports the version), checks the token, the
  renderer, the onboarding, the capability gate and `webSecurity`, and
  the desktop workflow runs it after installing. It found a real one:
  the embedded Python, with `import site` on, saw the building
  machine's user site-packages, so pip skipped dependencies that were
  "already there" and the installer shipped without them — the backend
  started on the developer's PC and died on a clean one. Provisioning
  and runtime now ignore the user site (`PYTHONNOUSERSITE=1`, `python
  -s`), and the embedded Python is installed from the repository source
  rather than from PyPI, so the installer carries this commit's code and
  dependencies.

- **The installer ships with the release, and the app updates itself.**
  `release.yml` gained a Windows job that, when a GitHub Release is
  published (after the test suite of the PyPI job passes), builds the
  installer, checks its version against the tag and attaches `GigaMail
  Setup X.Y.Z.exe`, its `.blockmap` and `latest.yml` to the Release.
  electron-builder's publish provider is `github`, so electron-updater
  reads that feed and the installed app picks up the next version. A
  downloaded update is announced with a notification and installed at
  the next quit; it no longer quits the app on a five-second timer.
  `publisherName` is out of the build config until the installer is
  signed — with it set, electron-updater refuses unsigned updates.

- **Console hardening.** Electron permissions are an explicit whitelist
  (microphone only, for dictation), every window carries a CSP without
  `unsafe-eval`, the mail iframe no longer lets popups escape the
  sandbox, and backend responses forbid scripts.

- **One version.** `console/package.json` follows `pyproject.toml`
  automatically at build time; the installer, the Python package and
  the release notes cannot disagree again.

- **Lint in CI**, and two bugs it found: a `NameError` silently dropping
  every message in the IMAP UID listing, and account deletion leaving
  the learned reply patterns behind.

## v0.2.4 — 2026-09-01

A day of using GigaMail on real mail, which is where the rest of these
were found. The recurring shape: something reported success, or reported
a capability it did not have, and only the phone or the customer found
out.

- **Rules can answer the person instead of the portal.** A listings site
  sends its notification from a relay (`reply@idealista.it`) and puts the
  enquirer's address in the body, so a semi-auto rule drafted a perfect
  reply and addressed it to a robot. Fixed addressing stays the default —
  it is what stops a hostile mail redirecting an answer via `Reply-To` —
  but a rule can now opt out with `reply_to_body_address`. The extracted
  address is shown in the approval preview, flagged as coming from the
  body, because it is the one field that does not come from an
  authenticated sender. No address found skips the message rather than
  falling back to the relay.

- **Rules carry cc and attachments.** Attachment names resolve against
  the account identity and are listed with real sizes in the preview; a
  name that no longer resolves skips the message instead of sending a
  mail that cites floor plans it does not have. `gigamail rules add`
  resolves them once at creation so a typo surfaces then, not a month
  later.

- **The watcher survives logout.** `scripts/watch-task.ps1` registers it
  with Task Scheduler, in the user's interactive session — never as
  SYSTEM, because account passwords are sealed with per-user DPAPI and
  approval toasts only exist inside a session. Stopping the task does not
  kill the tree it launched, which left two watchers competing over the
  same mail, so the launcher now asks `gigamail watch-running` first and
  that answer moved into `watcher.running_state()`, shared by console,
  CLI and task.

- **Telegram approvals actually work.** Requests raised by a tool arrived
  with no buttons, and tapping one answered "unknown request" because the
  handler required a rule row. Both fixed. Approving a tool request from
  the chat does not send — phase 2 belongs to the agent that asked — and
  the reply says so instead of implying the mail left.

- **Nothing in a Telegram approval is tappable except the buttons.**
  Without `parse_mode` Telegram linkifies addresses itself, so in a
  buttonless message the only thing to press was the recipient's
  `mailto:` — which opens the phone's mail client and asks you to sign
  in. An approval whose single affordance is an unexpected login prompt
  is indistinguishable from phishing, on the one channel with no Hello
  behind it. Addresses and URLs now go in `<code>`.

- **The chat shows the whole mail**, not just its subject: sender,
  recipients, cc, attachments and body, trimmed to fit Telegram's limit
  with the cut labelled. The toast can stay terse because it has a Leggi
  button; the chat has no second step.

- **A request that expired is not one that was decided.** The reply said
  "already decided or expired (pending)" — two contradictory things at
  once. The cases now read differently, and the buttons are stripped the
  moment you discover the request is dead, so the message stops offering
  actions that can only be refused.

- **No more announcing an approval that is switched off.** `notify.json`
  can say `approve: true` while no chat was ever recorded behind Windows
  Hello; the watcher logged "Telegram con approvazione" on the strength
  of the file alone, and the only way to learn otherwise was to tap
  Approva and be told no.

- **Optional PIN before approving from Telegram** (`gigamail telegram
  pin`, set and removed behind Hello). A tap alone means whoever holds
  the unlocked phone can send mail. Stored as scrypt with a random salt,
  three wrong tries lock the channel for 15 minutes, and the message
  carrying the PIN is deleted whether it was right or wrong. It is not
  Hello and does not pretend to be: the PIN crosses the chat in clear, so
  it guards against a phone left unlocked, not against someone who
  controls the Telegram account.

## v0.2.3 — 2026-08-31

Four bugs found by using GigaMail for a real morning of mail, not by
reading the code. Three of them shared a shape: the action reported
success and did the wrong thing quietly.

- **Approval toasts came out mute.** Every MCP tool creates its request
  through `require_approval()`, which notified without passing `actions`
  — so the toast was built with no buttons and the human saw an alert
  with nothing to press. Only the watcher's semi-auto path passed them,
  which is why the feature looked like it worked. Now every approval
  carries the same four: Leggi / Approva / Modifica / Rifiuta. **Leggi**
  shows the entire preview (no more 300-character truncation of a mail
  body) and lets you decide on the spot — reading and deciding are the
  same moment. **Modifica** rejects the request and hands back your note.
  Buttons still only open a `gigamail://` URL: Approva goes through
  Windows Hello exactly as before.

- **A second Python on the machine silenced the buttons.**
  `protocol_registered()` compared the HKLM registration with
  `sys.executable`, so the system Python next to the venv one produced a
  mute toast without a word. What matters is the *registered* command,
  not who is reading it.

- **Multi-recipient sends put one malformed address in the envelope.**
  `send_mail("a@x.it, b@y.it")` passed the string whole: SMTP issued a
  single `RCPT TO:<a@x.it, b@y.it>`, Graph a single `toRecipients`. The
  provider need not refuse it — ours didn't, returning `success: true`
  and `"accepted": 1`. Half the recipients were never in the envelope and
  nothing said so; the `To:` header was right, so the copy in Sent looked
  fine. `split_addresses()` (new `core/addresses.py`) is now used by
  SMTP, by Graph **and** by the preview you approve, so the list you
  approve and the envelope that leaves cannot drift apart.

- **`send_mail` and `reply_mail` can attach identity files.** Only files
  registered in that account's identity (price lists, floor plans),
  never an arbitrary path — otherwise send_mail is the easiest way to
  walk a file off the disk, and approval doesn't help, because the human
  approves a *name*. The preview lists name, path and real size of every
  attachment; a name that resolves to nothing aborts the request rather
  than sending a mail without the plan its body promises.

- **Dotted names resolved to the wrong file.**
  `os.path.splitext("B.7.3")` returns `("B.7", ".3")`, so a lookup for
  apartment B.7.3 searched for "B.7" and matched B.7.1, B.7.2, B.7.4 as
  well — first one wins. Silent: the mail went out carrying another
  apartment's floor plan. `read_knowledge_file` shares that function, so
  asking for one data sheet could return another. Fixed, and an
  ambiguous name now stops the request instead of guessing.

- **Toasts stayed put and stopped swallowing each other.** Five approvals
  raised in a row appeared as one: Windows collapses toasts from the same
  app unless each carries its own `tag`, so four vanished silently at the
  exact moment there were five decisions to make. The tag is now the
  request_id — and re-raising the *same* request replaces its toast
  instead of stacking a duplicate. The popup also no longer expires under
  you mid-read (`scenario='reminder'`: it stays until you decide; Windows
  offers no arbitrary duration, `duration='long'` tops out near 25s).
  The 15 minutes now live where they are real: the notification is born
  with the request's own TTL, so it sits in the action centre exactly as
  long as the approval is valid and removes itself when it dies — no
  Approva button on a request that can no longer be approved.

- **中文**: the README has a full Chinese section and the console speaks
  Chinese (language switch cycles IT → EN → 中; first-pass translation of
  all ~270 strings, with English fallback for anything missed — polish
  and corrections are very welcome: `console/i18n.js`).

- **Changing the Telegram chat revokes trust** (u/Secondmindsystems,
  r/mcp, within hours of the 0.2.1 post): the chat allowed to approve is
  the one recorded behind Windows Hello / Touch ID at `gigamail telegram
  setup --approve`, stored outside `notify.json`. If the configured
  chat_id stops matching it, the watcher disables Telegram approval,
  rejects every pending rule request (`decided_by:
  system:telegram-chat-changed`), alerts the previously trusted chat once,
  and audits the mismatch; approval returns only through the verified
  setup. His second point — an edited draft must invalidate the old
  approval — was already the behaviour (✏️ rejects the old request and
  creates a new request_id; approval binds to the canonical payload), now
  stated explicitly. Note: existing installs must re-run
  `gigamail telegram setup --approve` once to record the trusted chat.

## v0.2.1 — 2026-08-26

**The console catches up with 0.2.** Until now rules, the watcher and the
notification channels existed only in the CLI; the console still showed a
leftover "AI setup" panel (ChatGPT login / OpenAI API key) calling an
endpoint that no longer existed — a relic of the pre-GigaMail app and a
contradiction of "no built-in LLM".

- New **Automations** view: reply rules (list, create, pause, resume,
  delete, per-rule activity), watcher (status, start/stop, log) and a
  notifications/agent panel (which agent writes drafts, whether the human
  verification backend exists, desktop toast buttons with a one-click
  UAC setup, Telegram status).
- Same fence as the CLI: creating or resuming a rule from the console
  raises Windows Hello / Touch ID **in the backend** (`POST /rules`,
  `POST /rules/{id}/resume`) — the console token alone never pre-approves
  anything. Pausing and deleting need no prompt. The Telegram bot token
  is deliberately not enterable from the window (CLI only).
- Backend endpoints: `/rules*`, `/watch/status|start|stop|log`,
  `/notify/status`, `/notify/desktop-setup`. The watcher writes a
  heartbeat (pid, interval, last tick) so the console can tell "running"
  from "stale"; started from the console it runs detached and survives
  closing the window.
- Documents for a rule are chosen with the native file picker; only the
  chosen paths reach the backend.
- Removed: the ChatGPT/OpenAI "AI setup" modal and its i18n strings.

**An unreachable approval store now denies explicitly.** Both phases return
`status: store_unavailable` with a null `request_id`, and phase 2 never
calls the send function — it stays a deny even when the audit log itself
cannot be written. Behaviour under a missing store was already fail-closed
by exception; **u/ranbuman** (r/mcp) named why that is not enough on its
own: a bare exception reads as a bug, so the next person wraps it in a
try/except to quiet the logs and the gate becomes fail-open in a commit
that looks like cleanup. Six tests now turn red if that commit is ever
written. SECURITY.md documents it, including the one case where the hourly
cap does reset — delete the database and restart, which also drops every
pending and approved row: the cap moves, the gate does not.

## v0.2.0 — 2026-08-26 (tagged together with v0.2.1)

**Semi-auto and auto reply — rules with a fence around them.** The first
new capability since the gate: the user can declare, behind Windows Hello /
Touch ID, that mail from certain senders (or in a certain folder) gets a
drafted reply automatically — proposed for approval (`semi`) or sent within
strict limits (`auto`). Email autopilot is an existing category; what the
others don't ship is the fence. Design was published on r/mcp before the
code.

- **`gigamail watch`** — a new CLI process (the MCP server stays passive)
  that polls unread mail, matches rules, has the *user's own agent*
  (`agent_bridge`, default `claude -p`) draft the body, and turns it into a
  standard approval request. GigaMail still contains no LLM.
- **Rules live outside the agent's reach**: created, resumed and only
  manageable via `gigamail rules add/list/pause/resume/remove` — creation
  and reactivation require the OS-level human verification. There is no MCP
  tool that touches rules: a prompt injection cannot say "enable automode".
  Every rule has a mandatory expiry, a daily cap and a per-sender cooldown.
- **Fixed addressing**: the drafter produces the body and nothing else.
  Recipient, thread and subject are fixed by GigaMail from the incoming
  message — the reply goes to the authenticated `From` only, never to
  `Reply-To`, never to addresses written by the draft. An injection in the
  body has no exit channel.
- **Per-rule content**: the draft can only draw from the documents attached
  to that rule (plus the account identity) — no global knowledge, no mail
  search. Blast radius = the files you chose.
- **Deterministic anti-spam barriers, in front of the rules** (no LLM
  decides *whether* to reply): DMARC not `pass` → never `auto`; RFC 3834
  (Auto-Submitted, Precedence bulk/junk/list, List-Id/List-Unsubscribe,
  X-Auto-Response-Suppress, empty Return-Path, no-reply senders) → no reply
  at all; the provider's spam verdict is respected; executable/archive
  attachments and abnormal bodies never trigger; a burst of matches
  **pauses the rule by itself** (resume requires Hello); outgoing rule
  replies are marked `Auto-Submitted: auto-replied` over SMTP (Graph does
  not accept that header — declared, not faked).
- **first_contact: semi** by default — the first message from a new sender
  always goes through human approval, even on an `auto` rule; full auto for
  first contacts is an explicit per-rule opt-in.
- **auto = pre-approval, not self-approval**: the request is created
  already-approved with `decided_by automode:<rule_id>` — the human gave
  that approval behind Hello when creating the rule, for a precise scope,
  with an expiry. Same atomic consume→execute path, same audit, same
  `provider_result`; the pluggable notification (B5) fires either way.
- **Fixed live, day one**: replying through Microsoft Graph was broken —
  the `/reply` payload sent both `message.body` and `comment`, which Graph
  rejects (`SamePropertyContentConflictBody`). It failed as a bare
  `success: false`, because `reply_message` returned a boolean and threw
  the provider's answer away. Now `reply_message` returns the normalized
  result and `provider_result` reaches the audit for replies exactly as it
  does for sends — which is how the bug was found in the first live run of
  a rule (semi, Graph account, notification → Hello → sent, 202).
- **The notification now tells you everything** ("mail arrived from X,
  I propose this reply — approve?"): a new `{message}` placeholder carries
  the full human-readable text (sender, subject, draft body, the approve
  command) to the configured notify command; a **native desktop toast**
  (Windows/macOS/Linux) fires by default on every approval request —
  `GIGAMAIL_NOTIFY_DESKTOP=0` disables it. The notify command can now also
  live in `notify.json` next to `agent.json` (env var still wins), so it
  survives reboots. For `auto` rules the notification fires *after* the
  send, with the real outcome. Notification remains notification: no
  channel approves anything. Notifications speak **the user's language**
  (system locale, `GIGAMAIL_LANG` to override; it/en today) — while the
  *reply* language is chosen by the drafting agent from the incoming mail,
  two different audiences. Measured live on Windows 11: toasts from an
  unpackaged app are silently dropped until a Start-menu shortcut carries
  `System.AppUserModel.ID` — the registry key alone is not enough —
  so GigaMail registers itself (per-user shortcut + HKCU key,
  once, best-effort). Notification commands also survive short-lived
  processes now (`watch --once` no longer kills the notify thread
  mid-flight), and `notify.json` tolerates the BOM that Windows editors
  add.
- **Approve, reject or ask for changes from Telegram.** `gigamail telegram
  setup` (token typed, never an argument) makes Telegram a native channel:
  semi drafts arrive with ✅ / ❌ / ✏️ buttons; the watcher long-polls
  `getUpdates` between ticks and reacts in a second. Commands are accepted
  **only from the configured chat_id** — the Bot API cannot forge a
  message from a user, so a process on the PC cannot say yes for you.
  ✅ requires `--approve`, an explicit opt-in given behind Windows Hello /
  Touch ID (your phone becomes an approval device — see SECURITY.md);
  ❌ and ✏️ never need it. ✏️ asks for your changes, the drafter redoes
  the body with them (and the rejected draft as context), and the new
  draft goes through the gate again — always as semi, even on an `auto`
  rule. Audit: `decided_by: telegram:<chat_id>`; the trusted chat is
  written to the audit at every watcher start.
- **Clickable Windows notifications.** Semi drafts arrive as a toast with
  ✅ / ❌ buttons that open `gigamail://approve/<id>` — a URL scheme that
  launches the CLI, which raises Windows Hello. The toast never approves by
  itself; it opens the door. Measured live: toast buttons resolve custom
  schemes only from the *machine-level* registry (per-user registration is
  enough for the shell, not for toasts), so `gigamail desktop-setup` writes
  that key once behind a UAC prompt; until then toasts arrive without
  buttons (the text still says how to approve) rather than with a dead
  "Get an app" dialog.
- Watcher robustness from the live runs: rules now consider every message
  received after the rule was created, read or unread (a thread open in
  the mail client marks mail read before the watcher sees it) — a mail the
  user already read never goes `auto`, at most `semi`; a draft that times
  out (`claude -p` under load) is retried up to 3 times with a 300 s
  timeout (`GIGAMAIL_DRAFT_TIMEOUT`), then the user is told to reply by
  hand instead of a silent failure.
- **Tool descriptions rewritten for agents** (after glama.ai's Tool Score
  rated `create_folder` D and the `delete_*` tools C: one-line Italian
  descriptions, 0% parameter documentation, no annotations). All 24 tools
  now carry an English description that states purpose, side effects,
  prerequisites, what is returned and what to use instead; every
  parameter is documented in the schema; MCP annotations
  (`readOnlyHint` / `destructiveHint` / `idempotentHint` /
  `openWorldHint`) declare the risk class machine-readably and match the
  READ / WRITE_SAFE / DANGEROUS map. The six two-phase tools share one
  explicit contract text. Server `instructions` are in English too. A
  test keeps all of this from regressing.
- `gigamail rules add` also takes flags (`--senders/--folder`, `--style`,
  `--doc`, `--mode`, caps, expiry) and skips the questions; the Windows
  Hello / Touch ID prompt remains the one thing that cannot be scripted.
- New: `core/rules.py` (`.rules.db`), `core/mail_guard.py`, `watcher.py`,
  `get_message_headers` on both providers (IMAP `BODY.PEEK[HEADER]`, Graph
  `internetMessageHeaders`). 191 tests (was 160), including the
  anti-injection harness extended to rules: a hostile mail in a watched
  folder gets its reply sent only to its own sender, with only the
  drafter's text.

## v0.1.4 — 2026-08-19

**Approval now requires the person at the machine.** Three days after
v0.1.3, **u/ranbuman** (r/mcp) pointed out that "an agent with shell access
can run the approval CLI" is not a different threat model — it is exactly
the agent the gate exists to supervise: Claude Code, OpenClaw and Hermes
all hold a shell. He was right.

- Approving — `gigamail approvals approve <id>` **or** the console's
  `POST /approvals/{id}/approve` — now opens an OS-level user verification:
  **Windows Hello** (PIN/fingerprint/face) on Windows, **LocalAuthentication**
  (Touch ID/password) on macOS. A process can open that prompt; only the
  person at the machine can pass it. No code to type, no file to read, no
  screen to capture. `--yes` is gone. The console token alone no longer
  approves. **No backend, no approval** — the CLI refuses and the console
  returns 503 on machines without Windows Hello / LocalAuthentication.
  Rejecting never needs the prompt.
- Measured, not assumed (Windows 11): the prompt blocks until the human
  answers; a second request right after a successful one raises a **new**
  prompt — no sudo-style grace; it appears from a background process with
  no window. macOS reuse duration is set to 0. Details in SECURITY.md.

**The approval path no longer asserts what it has not verified.**

- **Cap on requests** (promised to u/Rebekator): the same payload with a
  live pending request returns the same `request_id` instead of a new one;
  more than `GIGAMAIL_APPROVAL_MAX_PER_HOUR` (20) per tool per hour →
  `rate_limited`, nothing created. An insisting agent cannot produce a burst
  of identical approvals.
- **Audit from the provider's response** (u/ranbuman): SMTP per-recipient
  refusals are read back from `sendmail()` and recorded as
  `provider_result` next to the approved payload — in the audit log and on
  the approval row (`execution_outcome`: ok / failed / dryrun). Graph
  returns 202 with no per-recipient result: recorded as such
  (`per_recipient_verified: false`), not faked.
- **Preview shows addresses, never display names**, and flags any
  recipient that is not an explicit SMTP address (bare name, group, list)
  as `may_expand` — the count you approve is not guaranteed.
- **SMTP TLS verified by default.** Port 465 used `CERT_NONE`; it now
  verifies, with per-account `insecure_tls` opt-out for self-signed servers.

**Notification.** `GIGAMAIL_APPROVAL_NOTIFY_CMD` (JSON argv with
`{request_id} {tool} {summary}`) runs on every new request — e.g.
`openclaw message send --channel telegram …` to reach you where your agent
lives. Notification only: it cannot approve. Run without a shell, best
effort, one per request (dedup does not re-notify).

**Also:** `GIGAMAIL_ROOT` / `GIGAMAIL_DATA_DIR` (ADE_* kept as aliases);
`GIGAMAIL_APPROVAL_TTL`; MCP server now identifies as `gigamail` with its
package version; console refuses to reuse a port-8002 backend that is not
GigaMail; Dependabot grouped; `server.json` for the official MCP Registry
(`io.github.adecubed/gigamail`) and a README note for agents installing on
a human's behalf.

Tests: 111 → 159. New dependency on Windows: `winrt-Windows.Security.
Credentials.UI` (Microsoft's PyWinRT projection); on macOS:
`pyobjc-framework-LocalAuthentication`.

## v0.1.3 — 2026-08-16

**Fix: data paths are now resolved in exactly one place.**

Six modules used to read `APPDATA` independently, each with its own
fallback (`~/ADE` for five of them, `~/.ade` for the sixth). Under an MCP
client that filters the environment of stdio subprocesses — Hermes passes
only a safe baseline, which does not include `APPDATA` on Windows — the
server silently opened an empty accounts DB and wrote approval requests to
a database the console and CLI never read. No error anywhere: the approval
gate failed silently.

All paths now come from `core/data_paths.py`:

- `ADE_ROOT` relocates everything (accounts, mail data, approvals, audit)
- `ADE_MAIL_DATA_DIR` relocates mail data only
- without `APPDATA`, the POSIX fallback is `~/.ade` — one directory, not two

With `APPDATA` present (any normal Windows setup) nothing moves: paths are
byte-identical to previous releases. Tests: 106 → 111.

**Verified integrations: OpenClaw and Hermes** (see INTEGRATIONS.md).
Tool discovery of all 24 tools verified against OpenClaw 2026.7.1-2
(`openclaw mcp add` + `probe`) and hermes-agent 0.19.0 (`hermes mcp test`),
both on Windows. End-to-end agent workflows on those two platforms are not
yet part of any claim.

## v0.1.2 — 2026-08-15

**Security fix: one approval could execute twice.** Consume was
SELECT-then-UPDATE, so two concurrent phase-2 calls could both see
"approved" and both execute — one human approval, two sends (8/8 with 8
concurrent calls in the regression test). Consume is now a single
conditional UPDATE; the identity of who approved is recorded in the audit
log.

Also: distribution renamed to **gigamail** on PyPI (`pip install
"gigamail[all]"`, verified from a clean venv against the real index),
publishing via GitHub trusted publisher (OIDC, no tokens), commands
`gigamail`, `gigamail-server`, `gigamail-console-api` with the legacy
`ade-mail-agent*` aliases kept.

## v0.1.1 — 2026-08-15

**Security fix: the agent could approve its own destructive actions.**

v0.1.0 returned a one-time confirmation token inside the tool result, which
put it in the model's context. The agent held both halves — the preview and
the key — so an instruction injected through an email could call the tool
again with the token it had just read. The gate stopped accidents, not a
determined injection. Reported on r/mcp by **u/ranbuman**; **u/anderson_the_one**
added the point about binding approval to the exact operation shown.

Approval is now **out of band**:

- a dangerous tool returns only `request_id`, an inert reference — no secret
  enters the model's context
- approval happens through channels the agent has no path to: the console
  API (behind its session token) or `gigamail approvals approve <id>`
- execution uses the canonical arguments stored when the request was made,
  never what the agent passes back at the second call
- repeating a `request_id` returns *awaiting approval*, indefinitely
- approvals live in SQLite, because requesting and approving now happen in
  different processes

New: `gigamail approvals list|approve|reject`, and `/approvals` endpoints on
the console API. Tool parameter renamed `confirm_token` → `request_id`.

Declared limitation: an agent with full shell access on the same machine can
run the approval CLI. That is a different threat model and GigaMail does not
claim to defend it.

Tests: 94 → 103, including one asserting that no MCP tool grants approval and
that the phase-1 payload contains no token. The red-team scenario now
instructs the agent to approve itself; with all tools live, it took no
destructive action.

## v0.1.0 — 2026-08-15

First public release. GigaMail is in daily production use at one company
(real estate: client enquiries answered with figures from our own files,
the right floor plans attached, and appointment slots from the calendar) —
but it is a 0.1: expect rough edges, and read the security model before
pointing it at a mailbox that matters.

### What's in it

**MCP server (stdio, no network port)** — 24 typed tools for an agent:

- *Read (15)*: accounts, identity, knowledge files, messages, unread,
  folders, hybrid search (provider + local index), attachment text, sender
  history, learned correction patterns, calendar events, free-slot
  availability
- *Safe writes (3, audited)*: mark read, move message, create folder
- *Destructive (6, two-phase)*: send, reply, delete message, delete folder,
  create/delete calendar event

**Permission model** — destructive tools never execute on the agent's word
alone: the first call returns a preview and a single-use token (5-minute
TTL), a human approves, the second call executes with the arguments that
were shown. Every write lands in an append-only action log. Login,
credentials and account management are CLI-only and never exposed as tools,
so a hostile email cannot reach them.

**Providers** — Microsoft Graph and IMAP/SMTP (Aruba, Gmail, Libero and any
IMAP server), Microsoft calendar, optional CalDAV configuration.

**Account context** — per-account identity (who you are, what you do, tone)
plus knowledge files you register: price lists, terms, product sheets. The
agent reads them to answer mail, and attachment suggestions follow what it
actually wrote.

**Human console (optional)** — Electron UI over a local HTTP API bound to
127.0.0.1 with a session token. What the old app delegated to an internal
LLM is now delegated to *your* agent through a bridge; there is no LLM
inside GigaMail.

**Privacy** — manual masking from the console (transparent MCP-side
filtering is planned). Mail indexes, credentials and memory stay on your
machine; content your agent reads is handled by that agent's provider.

### Quality

94 tests, green in CI on Windows and Linux across Python 3.10, 3.12 and
3.13. Anti-injection suite included: hostile emails ordering exfiltration,
mass deletion and self-approval with invented tokens were fed to a real
agent with all tools live — no destructive action occurred.

### Known limitations

- The action log is append-only but not tamper-proof.
- The bundled Azure app is not publisher-verified: the Microsoft consent
  screen shows an "unverified" notice. Bring your own `client_id` to avoid
  it; IMAP needs none of this.
- Gmail is supported via IMAP with an app password but has not been tested
  against a live account.
- Not on PyPI yet — install from a clone.
- The distribution/package name is still `ade-mail-agent` internally; the
  commands are `gigamail`, with the old names kept as aliases.
- `mark_spam`, `update_event`, `auth_status`, `search_contacts` and
  `list_followup_needed` are designed but not implemented.

### License

AGPL-3.0-or-later. Commercial licenses for closed-source use are available
from the copyright holder.
