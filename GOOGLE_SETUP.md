# Connecting Google (calendar and Drive)

GigaMail can serve the calendar from Google Calendar instead of Microsoft
Graph, and can put files on Google Drive. Both need one thing that no
amount of code can replace: an OAuth client belonging to **your** Google
Cloud project, shipped inside the build.

This page is the checklist. The Python side is already done.

> **Gmail is not this.** A Gmail mailbox is added as a normal IMAP account
> with an app password, from "Add account" in the console. Nothing on this
> page is needed for mail. What follows is only calendar and files.

---

## 1. The Google Cloud project

Everything here happens in the **Google Cloud console**,
<https://console.cloud.google.com/>. Not AI Studio: that issues API keys
for the Gemini models and has nothing to do with OAuth clients.

### Reusing a project you already have

You can, and you do not need a fresh one. But pick carefully, because
**the OAuth consent screen belongs to the project, not to the client**.
Every OAuth client in a project shares one consent screen, so:

- the app name on that screen is what people read when they authorise
  GigaMail — a project named after something else makes users hesitate;
- scopes accumulate on it, so adding the sensitive calendar scope to a
  project that is already verified reopens verification for whatever else
  lives there;
- verification status and the testing-mode user cap are per project.

Rule of thumb: reuse a project only if it has **no consent screen
configured yet**, or if it is already the GigaMail one. Anything already
published for another app deserves to be left alone. Checking takes half
a minute per project — **APIs & Services → OAuth consent screen** — and
you are looking at three things: publishing status, the user-facing app
name, and the scope list. A project blank on all three is a good
candidate. Projects created for you by AI Studio usually are not: they
exist to carry a Gemini API key.

### Then

1. Create or select the project at <https://console.cloud.google.com/>.
2. Enable two APIs: **Google Calendar API** and **Google Drive API**.
3. Configure the **OAuth consent screen**. Type "External" unless every
   user is inside one Workspace domain.
4. Add exactly these scopes, and no others:

   | Scope | What it grants | Google's classification |
   |---|---|---|
   | `openid` | sign-in | non-sensitive |
   | `.../auth/userinfo.email` | which account signed in | non-sensitive |
   | `.../auth/calendar.events` | read and write events | **sensitive** |
   | `.../auth/drive.file` | only files the app itself created | non-sensitive |

5. Create credentials: **OAuth client ID**, application type **Desktop
   app**. There is no redirect URI to fill in. A desktop client accepts
   any loopback port on `127.0.0.1`, which is what GigaMail uses.

## 2. Install the credentials

When you create the client, Google offers the credentials as a
downloadable JSON file. Hand that file to GigaMail rather than
transcribing anything:

```bash
gigamail google setup "C:\path\to\client_secret_....json"
```

It validates the file (a "Web application" client is rejected on the
spot, because it cannot accept the loopback redirect), copies it into the
GigaMail data directory and reports the project and client id.

**Do not copy the two values by hand.** Every Google secret starts with
`GOCSPX-` and they are all the same length, so the secret of one client
is visually indistinguishable from the secret of another. Pairing a right
id with a wrong secret yields `invalid_client` and nothing else to go on.

Where credentials are looked up, in order. **Each source must supply both
halves**; an incomplete one is skipped rather than topped up from the
next, precisely so that an id and a secret can never come from different
places:

1. `GOOGLE_CLIENT_ID` **and** `GOOGLE_CLIENT_SECRET`, for development.
2. The client JSON: the path in `GOOGLE_CLIENT_SECRETS`, the file
   installed by `gigamail google setup`, or a `client_secret_*.json` left
   in the data directory under its original name.
3. `src/ade_mail_agent/core/google_config.json`, shipped in the package.
   This is the one to fill for a public build: for a desktop client the
   secret is not really secret, and it travels in the package exactly
   like `client_id` in `ms_config.json`.

`gigamail google status` prints which of the three is in use.

## 3. Verification, and what it costs you

Until Google verifies the app it stays in **testing** mode: you add test
users by hand, up to a hundred, and each of them sees an "unverified app"
warning on the consent screen. That is fine for you and a few colleagues.
It is not fine for people who download GigaMail.

Two things follow from the scope choices above.

- `calendar.events` is sensitive, so verification is required, but **not**
  the third-party security assessment. Expect weeks of calendar time, not
  developer time.
- `drive.file` is deliberately not the full `drive` scope. Full Drive
  access is *restricted*, and restricted scopes trigger an annual CASA
  security assessment that costs money and repeats. Asking only for
  `drive.file` avoids it entirely. The price is real and worth knowing:
  GigaMail sees only the files it created itself, never the user's
  existing Drive.

Start verification early. It is the long pole, and it runs in parallel
with everything else.

## 4. Connect an account

From the console: **Add account → Calendar and Drive of Google**. The
browser opens, you authorise, the tab says you can close it.

From the CLI:

```bash
gigamail google login
```

Then check what is connected and which calendar is live:

```bash
gigamail google status
```

## 5. Choosing which calendar GigaMail uses

Connecting Google does **not** move your calendar. If you have a Microsoft
account, the calendar stays on Microsoft until you say otherwise. That is
deliberate: connecting Drive should never silently take your appointments
somewhere else.

To switch:

```bash
gigamail google calendar google
```

or the dropdown in the same console panel. `microsoft` switches back.

## 6. What works after this

- `list_events`, `find_free_slots`, `create_event` and `delete_event`
  keep their names and their shape. They follow whichever calendar is
  selected. Google events are normalised to the Microsoft Graph shape, so
  free-slot computation and the console calendar do not know the
  difference.
- `drive_list_files` and `drive_read_file` read; `drive_read_file`
  exports Docs, Sheets and Slides to Office formats so they extract like
  any attachment.
- `drive_upload_file` and `drive_delete_file` require human approval out
  of band, like sending mail. Deleting moves the file to the Drive trash,
  where the user can still recover it.

## 7. When it does not work

Every one of these came up during the first real setup. The error text
now names the remedy, but here is the map.

**`Access blocked: ... has not completed the Google verification process`,
`Error 403: access_denied`.** The app is in testing and the account you
signed in with is not in the test users list. Add it under **Audience →
Test users**, and make sure the browser is signed into that account.

**`Error 401: invalid_client`, "The OAuth client was not found"**, on the
Google sign-in page. The `client_id` does not exist. Usually a stale
browser tab from an earlier client, or a client that was deleted.

**`invalid_client`, "The provided client secret is invalid"**, after you
authorise. The `client_id` is right and the secret is not. Every Google
secret starts with `GOCSPX-` and is the same length, so two secrets from
two different clients look identical at a glance. Compare the characters
right after the prefix. The reliable fix is to take both values from the
same downloaded JSON file in one go.

**`403`, "Google Calendar API has not been used in project ... or it is
disabled".** Step 1 of this page was skipped, or only one of the two APIs
was enabled. Enabling Calendar does not enable Drive. Wait a couple of
minutes after enabling: Google says the change takes time to propagate,
and it does.

**`drive_list_files` returns nothing.** Expected. `drive.file` shows only
what GigaMail itself created. An empty list on a full Drive is the scope
working as designed, not a failure.

## 8. Revoking

`gigamail google logout` revokes the refresh token at Google and deletes
the local identity. The refresh token is stored in the same encrypted
account database as everything else (Fernet, with the key protected by
DPAPI on Windows). Access tokens are never written to disk.
