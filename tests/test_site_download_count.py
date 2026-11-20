"""The download total under the top bar's Download button
(docs/download-count.js): label, digits, endpoint and which clicks count.
How the board builds, flips and refreshes is tested with a DOM in
console/tests/site_download_board.test.js."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

DOCS = Path(__file__).resolve().parents[1] / "docs"
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node not installed")


def _run(body: str):
    script = (f"import * as dc from {json.dumps((DOCS / 'download-count.js').as_uri())};\n"
              f"const out = await (async () => {{ {body} }})();\n"
              "console.log(JSON.stringify(out));\n")
    res = subprocess.run([NODE, "--input-type=module", "-e", script],
                         capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout)


def test_labels_digits_and_url():
    out = _run("return [['en', 'it', 'zh-Hans', 'fr'].map(dc.labelFor),"
               " [13632, 0, null, 12.7].map(dc.digitsOf),"
               " dc.downloadsUrl({eventsEndpoint: 'https://api.example.com/event'}),"
               " dc.downloadsUrl({eventsEndpoint: ''})];")
    assert out == [["downloads", "download", "次下载", "downloads"],
                   ["13632", "", "", "12"], "https://api.example.com/downloads", ""]


def test_only_installer_clicks_count():
    base = "https://github.com/adecubed/gigamail/releases/latest"
    out = _run(f"return [{json.dumps(base + '/download/GigaMail-Setup.exe')},"
               f" {json.dumps(base + '/download/GigaMail-arm64.dmg')},"
               f" {json.dumps(base)}, 'https://github.com/adecubed/gigamail'].map(dc.isInstallerClick);")
    assert out == [True, True, False, False]


@pytest.mark.parametrize("fetch, expected", [
    ("() => Promise.resolve({ok: true, json: () => Promise.resolve({total: 13632})})", 13632),
    ("() => Promise.resolve({ok: true, json: () => Promise.resolve({total: null})})", None),
    ("() => Promise.reject(new Error('offline'))", None),
    ("() => Promise.resolve({ok: false})", None),
])
def test_fetch_total(fetch, expected):
    out = _run(f"return await dc.fetchTotal({fetch}, {{eventsEndpoint: 'https://api.example.com/event'}});")
    assert out == expected
