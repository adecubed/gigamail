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

Next to an existing `gigamail` install, in the same Python:

```bash
pip install "git+https://github.com/adecubed/gigamail#subdirectory=extras/real_estate"
gigamail extensions enable real_estate     # asks for Windows Hello / Touch ID
gigamail extensions list
```

For the Windows desktop app, use its embedded Python, from an
administrator prompt:
`"C:\Program Files\GigaMail\resources\python\python.exe" -m pip install ...`
**Known limitation:** an app update replaces the embedded Python, so the
extension has to be installed again after each update. Until that is
fixed, `gigamail extensions list` shows it as enabled but NOT INSTALLED,
and automatic drafts stop instead of going out unchecked.

An extension that is enabled but not installed is not skipped: automatic
drafts stop and the human is told, so a draft never goes out believed to
be checked when it was not.

## Tests

```bash
pip install -e extras/real_estate
pytest extras/real_estate/tests
```
