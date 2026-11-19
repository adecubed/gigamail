"""Build the data the site's email checker downloads (docs/email-check.html).

Two things, rebuilt every day by .github/workflows/checker-lists.yml and
published on the `checker-data` branch (no history: each run replaces it):

- known bad hosts (phishing and malware), as SHA-256 hashes split in 256
  shards by the first byte. The page fetches only the shards of the hosts in
  the mail it is checking, so it never downloads the whole list and never
  sends a host name anywhere.
- the most popular sites, so that famous domains are never called
  look-alikes and look-alikes of them can be spotted.

Sources (each named with its license in NOTICE.md of the branch):
Phishing.Database (MIT), phishing-filter by curben (lists CC BY-SA 4.0),
URLhaus by abuse.ch (CC0), the Tranco list.

    python scripts/build_checker_lists.py OUT_DIR
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import io
import json
import re
import sys
import urllib.request
import zipfile
from pathlib import Path

SOURCES = {
    "phishing-database": {
        "kind": "phishing",
        "urls": ["https://raw.githubusercontent.com/Phishing-Database/Phishing.Database/master/phishing-domains-ACTIVE.txt"],
        "license": "MIT, https://github.com/Phishing-Database/Phishing.Database",
    },
    "phishing-filter": {
        "kind": "phishing",
        "urls": ["https://malware-filter.gitlab.io/malware-filter/phishing-filter-domains.txt",
                 "https://curbengh.github.io/malware-filter/phishing-filter-domains.txt"],
        "license": "CC BY-SA 4.0, https://gitlab.com/malware-filter/phishing-filter (from OpenPhish and Phishing.Database)",
    },
    "urlhaus": {
        "kind": "malware",
        "urls": ["https://urlhaus.abuse.ch/downloads/hostfile/"],
        "license": "CC0, https://urlhaus.abuse.ch",
    },
}
TRANCO_URL = "https://tranco-list.eu/top-1m.csv.zip"
TRANCO_LICENSE = "Tranco, https://tranco-list.eu (built from Chrome UX Report, Cloudflare Radar and other rankings)"

TOP_PUBLISHED = 10_000      # popular sites the page downloads
TOP_PROTECTED = 100_000     # never listed as bad themselves
KINDS = {"phishing": 1, "malware": 2}

# Hosts where every customer gets a subdomain: a listed subdomain is one
# customer's site, not the platform, so those entries are kept.
USER_HOSTING = {
    "weebly.com", "wixsite.com", "blogspot.com", "000webhostapp.com", "firebaseapp.com", "web.app",
    "pages.dev", "workers.dev", "netlify.app", "vercel.app", "github.io", "gitlab.io", "glitch.me",
    "herokuapp.com", "azurewebsites.net", "wordpress.com", "square.site", "godaddysites.com",
    "webflow.io", "framer.website", "framer.app", "carrd.co", "mystrikingly.com", "jimdosite.com",
    "replit.app", "repl.co", "surge.sh", "onrender.com", "fly.dev", "appspot.com",
    "r2.dev", "ipfs.io", "dweb.link", "translate.goog", "my.canva.site", "canva.site",
}

HOST = re.compile(r"^(?=.{1,253}$)([a-z0-9_](?:[a-z0-9_-]{0,61}[a-z0-9_])?\.)+[a-z0-9-]{2,63}$")
IPV4 = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")


def base_domain(host: str) -> str:
    """Same rule as baseDomain in docs/email-check.js."""
    parts = [p for p in host.lower().rstrip(".").split(".") if p]
    if len(parts) <= 2:
        return ".".join(parts)
    two = parts[-2] in ("co", "com", "org", "net", "gov", "ac", "edu") and len(parts[-1]) == 2
    return ".".join(parts[-3:] if two else parts[-2:])


def parse_hosts(text: str) -> list[str]:
    """Host names from a blocklist: plain lines, hosts-file lines
    ("0.0.0.0 example.com"), comments and blank lines skipped."""
    out = []
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip().lower()
        if not line:
            continue
        fields = line.split()
        host = fields[-1] if len(fields) > 1 and IPV4.match(fields[0]) else fields[0]
        host = host.rstrip(".")
        if host in ("localhost", "0.0.0.0", "127.0.0.1"):
            continue
        if HOST.match(host) or IPV4.match(host):
            out.append(host)
    return out


def parse_tranco(data: bytes) -> list[str]:
    """Domains in rank order from Tranco's top-1m.csv(.zip): "rank,domain"."""
    if data[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            data = z.read(z.namelist()[0])
    out = []
    for line in data.decode("utf-8", "replace").splitlines():
        if "," in line:
            out.append(line.split(",", 1)[1].strip().lower())
    return out


def keep(host: str, protected: set[str], big: set[str]) -> bool:
    """Whether a listed host may be flagged. Popular sites themselves never
    are; nor are subdomains of the big sites (sites.google.com is in the
    lists because of pages hosted under it), except on platforms that give
    each customer a subdomain."""
    if host in protected:
        return False
    base = base_domain(host)
    if base in USER_HOSTING or any(host.endswith("." + h) for h in USER_HOSTING):
        return host != base and host not in USER_HOSTING
    return base not in big


def digest(host: str) -> bytes:
    return hashlib.sha256(host.encode("utf-8")).digest()


def build(bad: dict[str, list[str]], tranco: list[str], out: Path, fetched: dict[str, str]) -> dict:
    """Write the shards, the popular list, meta.json and NOTICE.md."""
    protected = set(tranco[:TOP_PROTECTED])
    big = set(tranco[:1000])
    kinds: dict[str, int] = {}
    counts = {}
    for name, hosts in bad.items():
        flag = KINDS[SOURCES[name]["kind"]]
        kept = 0
        for h in hosts:
            if keep(h, protected, big):
                kinds[h] = kinds.get(h, 0) | flag
                kept += 1
        counts[name] = kept
    shards: dict[int, list[bytes]] = {i: [] for i in range(256)}
    for host, flag in kinds.items():
        d = digest(host)
        shards[d[0]].append(d[1:9] + bytes([flag]))
    (out / "bad").mkdir(parents=True, exist_ok=True)
    for i, rows in shards.items():
        (out / "bad" / f"{i:02x}.bin").write_bytes(b"".join(sorted(rows)))
    (out / "top.txt").write_text("\n".join(tranco[:TOP_PUBLISHED]) + "\n", encoding="utf-8")
    meta = {
        "built": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
        "bad_hosts": len(kinds),
        "per_source": counts,
        "top": min(TOP_PUBLISHED, len(tranco)),
        "fetched": fetched,
        "format": "bad/XX.bin: rows of 9 bytes, sorted: bytes 1-8 of SHA-256(host) and a flag "
                  "(1 phishing, 2 malware); XX is byte 0 in hex",
    }
    (out / "meta.json").write_text(json.dumps(meta, indent=1) + "\n", encoding="utf-8")
    notice = ["# Data for the gigamail.ai email checker", "",
              "Rebuilt daily by .github/workflows/checker-lists.yml in adecubed/gigamail.", "",
              "Known bad hosts come from:", ""]
    notice += [f"- {n}: {SOURCES[n]['license']}" for n in bad]
    notice += ["", f"Popular sites: {TRANCO_LICENSE}.", "",
               "The hashed lists are an adaptation of those sources and are shared under the same terms: "
               "CC BY-SA 4.0 for what comes from phishing-filter.", ""]
    (out / "NOTICE.md").write_text("\n".join(notice), encoding="utf-8")
    return meta


def fetch(urls: list[str]) -> tuple[bytes, str]:
    last = None
    for url in urls:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "gigamail-checker-lists"})
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.read(), url
        except Exception as e:  # try the next mirror
            last = e
    raise RuntimeError(f"no source reachable: {urls}: {last}")


def main(argv: list[str]) -> int:
    out = Path(argv[1] if len(argv) > 1 else "checker-data")
    bad, fetched = {}, {}
    for name, src in SOURCES.items():
        try:
            data, url = fetch(src["urls"])
            bad[name] = parse_hosts(data.decode("utf-8", "replace"))
            fetched[name] = url
        except RuntimeError as e:
            print(f"warning: {name} skipped: {e}", file=sys.stderr)
    data, url = fetch([TRANCO_URL])
    tranco = parse_tranco(data)
    fetched["tranco"] = url
    if len(tranco) < 100_000 or not bad:
        print("refusing to publish: a source came back too small", file=sys.stderr)
        return 1
    meta = build(bad, tranco, out, fetched)
    print(json.dumps(meta, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
