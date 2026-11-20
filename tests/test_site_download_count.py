"""The download total under the download buttons (docs/download-count.js):
its wording per language, and that nothing shows until the backend knows
the total."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

DOCS = Path(__file__).resolve().parents[1] / "docs"
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node not installed")

FAKE_DOC = """
function fakeDoc(lang, rows) {
  const added = [];
  return {added, documentElement: {lang},
    querySelectorAll: () => Array.from({length: rows}, () => ({after: p => added.push(p.textContent)})),
    createElement: () => ({})};
}
const reply = body => () => Promise.resolve({ok: true, json: () => Promise.resolve(body)});
"""


def _run(body: str):
    script = (f"import * as dc from {json.dumps((DOCS / 'download-count.js').as_uri())};\n"
              + FAKE_DOC + f"const out = await (async () => {{ {body} }})();\n"
              "console.log(JSON.stringify(out));\n")
    res = subprocess.run([NODE, "--input-type=module", "-e", script],
                         capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout)


def test_wording_per_language():
    out = _run("return ['en', 'it', 'zh-Hans', 'fr'].map(l => dc.countText(13632, l));")
    assert out == ["13,632 downloads · desktop app and PyPI",
                   "13.632 download · app desktop e PyPI",
                   "13,632 次下载 · 桌面应用和 PyPI",
                   "13,632 downloads · desktop app and PyPI"]


def test_url_comes_from_the_events_endpoint():
    out = _run("return [dc.downloadsUrl({eventsEndpoint: 'https://api.example.com/event'}),"
               " dc.downloadsUrl({eventsEndpoint: ''})];")
    assert out == ["https://api.example.com/downloads", ""]


def test_shown_under_every_row_of_buttons():
    out = _run("const d = fakeDoc('en', 3);"
               " await dc.showDownloadCount(d, reply({total: 13632}), {eventsEndpoint: 'https://api.example.com/event'});"
               " return d.added;")
    assert out == ["13,632 downloads · desktop app and PyPI"] * 3


@pytest.mark.parametrize("fetch", [
    "reply({total: null, github: 510, pypi: null})",
    "() => Promise.reject(new Error('offline'))",
    "() => Promise.resolve({ok: false})",
])
def test_nothing_shown_without_a_full_total(fetch):
    out = _run(f"const d = fakeDoc('en', 2);"
               f" await dc.showDownloadCount(d, {fetch}, {{eventsEndpoint: 'https://api.example.com/event'}});"
               " return d.added;")
    assert out == []
