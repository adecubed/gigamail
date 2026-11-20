"""The download total under the top bar's Download button
(docs/download-count.js): its digits and label, and that nothing shows until
the backend knows the total."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

DOCS = Path(__file__).resolve().parents[1] / "docs"
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node not installed")

FAKE = """
const CONFIG = {eventsEndpoint: 'https://api.example.com/event'};
const reply = body => () => Promise.resolve({ok: true, json: () => Promise.resolve(body)});
function el(tag) {
  return {tag, children: [], textContent: '', attrs: {}, className: '',
    classList: {add() {}, remove() {}, toggle() {}},
    setAttribute(k, v) { this.attrs[k] = v; },
    append(...c) { this.children.push(...c); },
    replaceWith(x) { this.replacedBy = x; }};
}
function fakePage(lang, withButton = true) {
  const button = el('a');
  return {button, doc: {documentElement: {lang},
            querySelector: () => (withButton ? button : null), createElement: el}};
}
const WIN = {scrollY: 0, addEventListener() {}, setInterval: () => 0, clearInterval() {},
             matchMedia: () => ({matches: true})};
"""


def _run(body: str):
    script = (f"import * as dc from {json.dumps((DOCS / 'download-count.js').as_uri())};\n"
              + FAKE + f"const out = await (async () => {{ {body} }})();\n"
              "console.log(JSON.stringify(out));\n")
    res = subprocess.run([NODE, "--input-type=module", "-e", script],
                         capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout)


def test_labels_and_digits():
    out = _run("return [['en', 'it', 'zh-Hans', 'fr'].map(dc.labelFor),"
               " [13632, 0, null, 12.7].map(dc.digitsOf), dc.downloadsUrl(CONFIG)];")
    assert out == [["downloads", "download", "次下载", "downloads"],
                   ["13632", "", "", "12"], "https://api.example.com/downloads"]


def test_board_under_the_download_button():
    out = _run("""
      const {doc, button} = fakePage('it');
      const shown = await dc.showDownloadBoard(doc, WIN, reply({total: 13632}), CONFIG);
      const wrap = button.replacedBy, board = wrap.children[1];
      const [tiles] = board.children;
      return [shown, wrap.children[0] === button, board.attrs['aria-label'],
              tiles.children.map(t => t.textContent).join(''), board.children.length];
    """)
    assert out == ["13632", True, "13632 download", "13632", 1]


@pytest.mark.parametrize("fetch", [
    "reply({total: null, github: 510, pypi: null})",
    "() => Promise.reject(new Error('offline'))",
    "() => Promise.resolve({ok: false})",
])
def test_nothing_shown_without_a_full_total(fetch):
    out = _run(f"const {{doc, button}} = fakePage('en');"
               f" const shown = await dc.showDownloadBoard(doc, WIN, {fetch}, CONFIG);"
               " return [shown, button.replacedBy === undefined];")
    assert out == ["", True]
