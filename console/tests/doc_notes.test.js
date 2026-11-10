// Unit tests of doc_notes.js: the rule form and the rule cards say what the
// agent will not read well in a rule's documents.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { JSDOM } = require('jsdom');

function load(lang) {
  const dom = new JSDOM('<!DOCTYPE html><body><div id="box" style="display:none"></div></body>',
    { runScripts: 'outside-only', url: 'http://localhost/' });
  const w = dom.window;
  w.localStorage.setItem('ade_lang', lang || 'en');
  vm.runInContext(fs.readFileSync(path.join(__dirname, '..', 'doc_notes.js'), 'utf-8'),
    dom.getInternalVMContext());
  return w;
}

const box = (w) => w.document.getElementById('box');

const REPORTS = [
  { name: 'terms.txt', notes: [] },
  { name: 'list.xlsx', notes: [
    { code: 'sheets', names: ['Available', 'Old prices'] },
    { code: 'too_long', chars: 45000, limit: 30000 },
  ] },
  { name: 'plan.pdf', notes: [{ code: 'no_text' }] },
];

test('every note becomes a sentence under the name of its document', () => {
  const w = load('en');
  const lines = w.DocNotes.lines(REPORTS);
  assert.equal(lines.map((l) => l.name).join('|'), 'list.xlsx|list.xlsx|plan.pdf');
  assert.match(lines[0].text, /2 sheets \(Available, Old prices\)/);
  assert.match(lines[1].text, /45,000 characters.*30,000/);
  assert.match(lines[2].text, /attach it, not read it/);
});

test('the sentences follow the language of the console', () => {
  const it = load('it').DocNotes.lines(REPORTS);
  assert.match(it[0].text, /ha 2 fogli/);
  const zh = load('zh').DocNotes.lines(REPORTS);
  assert.match(zh[0].text, /2 个工作表/);
});

test('a document with nothing to say leaves the box hidden', () => {
  const w = load('en');
  w.DocNotes.fill(box(w), [{ name: 'terms.txt', notes: [] }]);
  assert.equal(box(w).style.display, 'none');
  assert.equal(box(w).children.length, 0);
});

test('names and sheet titles are written as text, never as markup', () => {
  const w = load('en');
  w.DocNotes.fill(box(w), [{ name: '<img src=x onerror=1>.xlsx',
    notes: [{ code: 'sheets', names: ['<b>a</b>', 'b'] }] }]);
  assert.equal(box(w).style.display, '');
  assert.equal(box(w).querySelector('img'), null);
  assert.equal(box(w).querySelector('b'), null);
  assert.match(box(w).textContent, /<img src=x onerror=1>\.xlsx/);
});

test('show asks the backend for the paths and draws only the latest answer', async () => {
  const w = load('en');
  const calls = [];
  let release;
  const slow = new Promise((r) => { release = r; });
  const api = async (url, opts) => {
    calls.push([url, JSON.parse(opts.body).paths]);
    if (calls.length === 1) { await slow; return [{ name: 'old.xlsx', notes: [{ code: 'no_text' }] }]; }
    return [{ name: 'new.xlsx', notes: [{ code: 'no_text' }] }];
  };
  const first = w.DocNotes.show(box(w), ['a'], api);
  await w.DocNotes.show(box(w), ['b'], api);
  release();
  await first;
  assert.deepEqual(calls, [['/documents/check', ['a']], ['/documents/check', ['b']]]);
  assert.match(box(w).textContent, /new\.xlsx/);
  assert.doesNotMatch(box(w).textContent, /old\.xlsx/);
});

test('no documents, or a backend that does not answer: nothing is claimed', async () => {
  const w = load('en');
  w.DocNotes.fill(box(w), REPORTS);
  await w.DocNotes.show(box(w), [], async () => { throw new Error('unused'); });
  assert.equal(box(w).style.display, 'none');
  await w.DocNotes.show(box(w), ['a'], async () => { throw new Error('down'); });
  assert.equal(box(w).children.length, 0);
});
