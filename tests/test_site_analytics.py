"""The site's visit counter (docs/business/analytics.js): which source and
which kind of device a visit or a download click reports. It runs in the
visitor's browser; here it runs under Node with a fake window."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

DOCS = Path(__file__).resolve().parents[1] / "docs"
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node not installed")

FAKE = """
const config = {eventsEndpoint: 'https://events.example.com/event', site: 'gigamail',
                productionHosts: ['gigamail.ai', 'www.gigamail.ai']};
function fakeWindow(href, store = {}) {
  const sent = [];
  return {
    sent, store,
    location: new URL(href),
    navigator: {userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)', language: 'en-US', maxTouchPoints: 0},
    sessionStorage: {getItem: k => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = String(v); }},
    fetch: (url, opts) => { sent.push(JSON.parse(opts.body)); return Promise.resolve(); },
  };
}
"""


def _run(body: str):
    script = (
        f"import * as an from {json.dumps((DOCS / 'business' / 'analytics.js').as_uri())};\n"
        + FAKE
        + f"const out = await (async () => {{ {body} }})();\n"
        "console.log(JSON.stringify(out));\n"
    )
    res = subprocess.run([NODE, "--input-type=module", "-e", script],
                         capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout)


@pytest.mark.parametrize("ua, touch, expected", [
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64)", 0, ["desktop", "windows"]),
    ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)", 0, ["desktop", "mac"]),
    ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)", 5, ["tablet", "ios"]),
    ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)", 5, ["mobile", "ios"]),
    ("Mozilla/5.0 (Linux; Android 15; Pixel 9) Mobile Safari/537.36", 5, ["mobile", "android"]),
    ("Mozilla/5.0 (Linux; Android 15; SM-X710) Safari/537.36", 5, ["tablet", "android"]),
    ("Mozilla/5.0 (X11; Linux x86_64)", 0, ["desktop", "linux"]),
])
def test_device_info(ua, touch, expected):
    out = _run(f"const d = an.deviceInfo({{userAgent: {json.dumps(ua)}, maxTouchPoints: {touch}}});"
               " return [d.device, d.os];")
    assert out == expected


def test_landing_keeps_source_across_pages_of_the_site():
    out = _run("""
      const store = {};
      const first = an.landing(config, fakeWindow('https://gigamail.ai/?utm_source=reddit&utm_campaign=desktop', store),
                               {referrer: 'https://www.reddit.com/'});
      const next = an.landing(config, fakeWindow('https://gigamail.ai/install.html', store),
                              {referrer: 'https://gigamail.ai/'});
      const fresh = an.landing(config, fakeWindow('https://gigamail.ai/', {}), {referrer: 'https://t.co/'});
      return {first, next, fresh};
    """)
    assert out["first"] == {"referrer": "www.reddit.com", "utm_source": "reddit", "utm_campaign": "desktop"}
    assert out["next"] == out["first"]
    assert out["fresh"] == {"referrer": "t.co", "utm_source": "", "utm_campaign": ""}


def test_visit_and_download_carry_source_and_device():
    out = _run("""
      const win = fakeWindow('https://gigamail.ai/?utm_source=reddit');
      const doc = {referrer: '', listeners: [], addEventListener(t, f) { this.listeners.push(f); }};
      an.trackVisit(config, win, doc);
      an.trackDownloads(config, win, doc);
      const link = {href: 'https://github.com/adecubed/gigamail/releases/latest/download/GigaMail-Setup.exe'};
      doc.listeners[0]({target: {closest: () => link}});
      return win.sent;
    """)
    visit, download = out
    assert visit["type"] == "visita" and visit["utm_source"] == "reddit"
    assert (visit["device"], visit["os"]) == ("desktop", "windows")
    assert download["type"] == "download" and download["text"] == "win"
    assert (download["utm_source"], download["device"], download["os"]) == ("reddit", "desktop", "windows")


def test_nothing_is_sent_with_do_not_track():
    out = _run("""
      const win = fakeWindow('https://gigamail.ai/');
      win.navigator.doNotTrack = '1';
      return an.track('visita', {}, config, win) || win.sent.length;
    """)
    assert out == 0


@pytest.mark.parametrize("href, referrer, reload, expected", [
    ("https://gigamail.ai/", "https://www.reddit.com/", False, "visita"),
    ("https://gigamail.ai/", "", False, "visita"),
    ("https://gigamail.ai/install.html", "https://gigamail.ai/", False, "pagina"),
    ("https://gigamail.ai/?utm_source=reddit", "https://gigamail.ai/", False, "visita"),
    ("https://gigamail.ai/", "https://www.reddit.com/", True, "pagina"),
])
def test_only_the_arrival_is_a_visit(href, referrer, reload, expected):
    out = _run(f"""
      const win = fakeWindow({json.dumps(href)});
      win.performance = {{getEntriesByType: () => [{{type: {json.dumps('reload' if reload else 'navigate')}}}]}};
      an.trackVisit(config, win, {{referrer: {json.dumps(referrer)}}});
      return win.sent[0].type;
    """)
    assert out == expected
