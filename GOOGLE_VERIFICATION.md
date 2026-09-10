# Submitting GigaMail for Google verification

Until Google verifies the app it stays in testing: only hand-added test
users can sign in, and each of them sees an "unverified app" warning.
This page is the submission pack. Written 10 September 2026 for project
`gigamail-508208`.

Only one scope drives the whole process:

| Scope | Class | Consequence |
|---|---|---|
| `openid`, `userinfo.email` | non-sensitive | nothing |
| `drive.file` | non-sensitive | nothing |
| `calendar.events` | **sensitive** | verification required |

Because `drive.file` was chosen over full `drive`, no scope here is
*restricted*, so the annual third-party CASA security assessment does not
apply. Keep it that way: widening Drive access later changes the cost of
every future release.

---

## Before you open the form

1. **Verify the domain.** `gigamail.ai` must be verified in
   [Google Search Console](https://search.google.com/search-console) under
   the same Google account that owns the Cloud project, then listed as an
   authorized domain on the consent screen. Verification fails at once
   without this.
2. **Publish the privacy policy.** `docs/privacy.html` goes live at
   `https://gigamail.ai/privacy.html` when the repository is pushed, since
   the site is served from `docs/`. Check it loads before submitting.
3. **Complete the branding.** App name, logo and support email on the
   consent screen must match the homepage. The app name is what users read
   when they authorise, so it must be *GigaMail*, not a project codename.
4. **Record the demo video** (see below).

Then submit from **Google Auth Platform → Verification Center**.

---

## Scope justification

Paste this where the form asks why the app needs `calendar.events`.

> GigaMail is a local, open-source MCP server that gives a user's own AI
> agent controlled access to their mailbox. Scheduling is the part of
> email that the agent cannot do without a calendar.
>
> The application uses `calendar.events` for two things. It reads events
> in a short forward window to compute genuinely free meeting slots, so
> that when a correspondent asks to meet, the drafted reply proposes times
> the user is actually available, instead of times the model invented.
> And it creates or deletes an event once the user has agreed to a time in
> that conversation.
>
> Only events are needed, which is why the narrower `calendar.events`
> scope is requested rather than full calendar management: the application
> never creates, shares, deletes or changes the settings of a calendar.
>
> Every write is gated. Creating or deleting an event returns a preview
> and waits for a human approval given out of band, behind the operating
> system's own authentication (Windows Hello or Touch ID). The AI agent
> cannot grant that approval and cannot proceed without it.
>
> All data stays on the user's machine. GigaMail operates no servers and
> receives no user data.

If the form also asks about `drive.file`:

> `drive.file` lets GigaMail file documents it produces from email —
> generated attachments, exported threads — into the user's Drive, and
> read back the ones it created. It grants no access to the user's
> existing Drive contents, which the application neither needs nor wants.
> Uploading and trashing both require the same out-of-band human approval
> as sending mail.

---

## The demo video

Google needs an unlisted YouTube video. Reviewers reject videos that skip
the consent screen or that show a scope being requested but never used.
Show, in this order, with no cuts inside a step:

1. **The OAuth consent screen**, with the client id legible in the browser
   address bar. This is what proves the video is of this project.
2. **Granting consent** and landing back in GigaMail connected.
3. **`calendar.events` being read**: an incoming email asking to meet, and
   the agent proposing real free slots taken from the calendar.
4. **`calendar.events` being written**: creating the event, and the
   approval request stopping it until a human approves out of band.
5. **`drive.file`**: uploading a document to Drive, again through the
   approval gate, then listing it back.
6. **Revocation**: disconnecting the account from the console or with
   `gigamail google logout`.

Narrate what each step does. Silent screen recordings get sent back.

---

## What to expect

Weeks, not days, and usually at least one round of questions. Common
reasons for a first rejection, all avoidable:

- privacy policy not on the same domain as the homepage, or not
  mentioning Google user data specifically;
- the homepage not making it clear what the application actually does;
- a video that shows the consent screen but never the scope in use;
- an app name or logo that does not match the site.

Nothing about the software has to change while you wait. The app keeps
working for test users throughout.
