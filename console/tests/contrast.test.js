// contrast.test.js — i testi grigi restano leggibili (WCAG AA, 4.5:1 su bianco).
//
// Segnalazione su r/UXDesign (u/Mrmasseno) alla 0.3.0: date, didascalie e
// segnaposto stavano a nero 30-45%, cioe' 2.1-3.4:1. Questo test scansiona
// i sorgenti della console: ogni `color: rgba(0,0,0,a)` di testo e i token
// --text-* devono avere contrasto >= 4.5 sul bianco.
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');

const ROOT = path.join(__dirname, '..');
const FILES = fs.readdirSync(ROOT)
  .filter((f) => /\.(html|js|css)$/.test(f) && !/^(eslint\.config|sync-version)\.js$/.test(f))
  .map((f) => path.join(ROOT, f));

function luminance([r, g, b]) {
  const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
  return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
}
function contrastOnWhite(rgb) {
  return (1 + 0.05) / (luminance(rgb) + 0.05);
}
// nero con alpha a, composto su bianco
const blackAlpha = (a) => { const v = Math.round(255 * (1 - a)); return [v, v, v]; };

// color: di testo (non background-color / border-color / outline-color)
const TEXT_RGBA = /(?<![-\w])color:\s*rgba\(0,\s*0,\s*0,\s*(0?\.\d+)\)/g;

test('nessun testo grigio sotto 4.5:1 su bianco', () => {
  const bad = [];
  for (const f of FILES) {
    const src = fs.readFileSync(f, 'utf-8');
    for (const m of src.matchAll(TEXT_RGBA)) {
      const a = parseFloat(m[1]);
      const c = contrastOnWhite(blackAlpha(a));
      if (c < 4.5) bad.push(`${path.basename(f)}: rgba(0,0,0,${a}) = ${c.toFixed(2)}:1`);
    }
  }
  assert.deepStrictEqual(bad, [], 'testi sotto AA:\n' + bad.join('\n'));
});

test('token --text-* della console sopra AA', () => {
  const css = fs.readFileSync(path.join(ROOT, 'style_v2.css'), 'utf-8');
  const tokens = [...css.matchAll(/--text-[\w-]+:\s*rgba\(0,\s*0,\s*0,\s*(0?\.\d+)\)/g)];
  assert.ok(tokens.length >= 4, 'attesi almeno primary/secondary/tertiary/muted');
  for (const m of tokens) {
    const c = contrastOnWhite(blackAlpha(parseFloat(m[1])));
    assert.ok(c >= 4.5, `${m[0]} -> ${c.toFixed(2)}:1`);
  }
});
