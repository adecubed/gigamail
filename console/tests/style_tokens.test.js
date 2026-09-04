// style_tokens.test.js — il restyle 0.3.1 non torna indietro.
//
// Da r/UXDesign (AbilityRadiant2342, el_paro): bordi chiari invece del nero
// al 75%, ombre leggere, nessun testo sopra un gradiente. Il gradiente
// rosa-blu resta solo su avatar, logo, stati del microfono e iconcine.
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');

const ROOT = path.join(__dirname, '..');
const FILES = fs.readdirSync(ROOT)
  .filter((f) => /\.(html|js|css)$/.test(f) && !/^(eslint\.config|sync-version)\.js$/.test(f))
  .map((f) => path.join(ROOT, f));
const read = (f) => fs.readFileSync(f, 'utf-8');

test('nessun bordo nero al 75% o "solid black"', () => {
  const bad = [];
  for (const f of FILES) {
    const src = read(f);
    const n = (src.match(/solid rgba\(0,\s*0,\s*0,\s*0\.75\)|solid black\b|border-color:\s*rgba\(0,\s*0,\s*0,\s*0\.75\)/g) || []).length;
    if (n) bad.push(`${path.basename(f)}: ${n}`);
  }
  assert.deepStrictEqual(bad, []);
});

test('gradiente rosa-blu solo su avatar, logo, voce e iconcine', () => {
  const GRAD = /linear-gradient\(135deg,#eeb9dd,#b0c7f4\)|linear-gradient\(135deg,#b0c7f4,#eeb9dd\)/g;
  let total = 0;
  for (const f of FILES) total += (read(f).match(GRAD) || []).length;
  // style_v2.css: .s-avatar + 2 stati voce; renderer_utils.js: pallino + icona calendario
  assert.ok(total <= 5, `gradiente rosa-blu in ${total} punti: e' tornato sotto un testo?`);
});

test('nessuna ombra pesante', () => {
  const bad = [];
  for (const f of FILES) {
    const n = (read(f).match(/box-shadow:\s*0 [46]px (?:1[46]|20)px rgba\((?:0,\s*0,\s*0|7, 7, 7|18, 18, 18|57, 56, 56|13, 13, 13),\s*0\.(?:35|4|5|6)\)/g) || []).length;
    if (n) bad.push(`${path.basename(f)}: ${n}`);
  }
  assert.deepStrictEqual(bad, []);
});
