# gigamail-real-estate

GigaMail extension for real-estate agencies. It grew out of the agency
where GigaMail runs every day, answering enquiries from property portals
and from the agency's own website. It is not part of the `gigamail`
package: install it only if you sell homes.

What it adds on top of the core:

- **Flat type check.** The requested type (monolocale, bilocale,
  trilocale…) is read deterministically from the listing title the portal
  puts in the subject. It goes into the draft prompt as a constraint, and
  the draft is checked before it reaches the human: if the agent proposes
  another type, the watcher has it redrafted once with a concrete
  correction, and stops if it gets it wrong again.
- **Unit codes.** Codes such as `A.3.2` or `B.1.4` cited in the draft
  decide which data sheets and floor plans are attached, instead of a
  fixed list in the rule.

## Install

```bash
gigamail extensions install real_estate    # asks for Windows Hello / Touch ID
gigamail extensions enable real_estate     # asks again: it changes what the watcher does
gigamail extensions list
```

`install` puts the extension in the user's data folder
(`%APPDATA%\ADE\extensions`, `~/.ade/extensions`), not in the Python that
runs GigaMail. App updates replace that Python; the data folder survives
them, so the extension is installed once. No administrator rights, no git.

It is taken from the GitHub tag of the installed gigamail version, so
extension and core come from the same commit. `--ref main` takes it from a
branch instead.

With the Windows desktop app the CLI is in the app's own Python:

```bat
"C:\Program Files\GigaMail\resources\python\python.exe" -m ade_mail_agent.cli extensions install real_estate
"C:\Program Files\GigaMail\resources\python\python.exe" -m ade_mail_agent.cli extensions enable real_estate
```

An extension that is enabled but not installed is not skipped: automatic
drafts stop and the human is told, so a draft never goes out believed to
be checked when it was not.

## Tests

```bash
pip install -e extras/real_estate
pytest extras/real_estate/tests
```
