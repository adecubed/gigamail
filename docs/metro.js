// metro.js — Mail City as a metro map. Five lines, one per thing a visitor
// may want to do; every stop is a feature GigaMail has today (the texts
// follow features.html and security.html). A train rides the chosen line,
// the camera follows it, and the card of the station it stops at lifts off
// the map. Interchanges are stations shared by two or more lines.
// No real mail is touched: this is a drawing.
const it = document.documentElement.lang === 'it';
const $ = id => document.getElementById(id);
const calm = matchMedia('(prefers-reduced-motion: reduce)').matches;
const NS = 'http://www.w3.org/2000/svg';
const el = (t, a, p) => { const e = document.createElementNS(NS, t); for (const k in a) e.setAttribute(k, a[k]); if (p) p.appendChild(e); return e; };

const COL = { y: '#e2a72e', g: '#2f9a5c', r: '#d6453b', b: '#2f6fc0', p: '#8a5cc2' };

// [x, y, card x, card y, lines]
const GEO = {
  inbox: [100, 600, 20, 470, 'ygrp'], masker: [280, 600, 200, 470, 'pygr'], llm: [460, 600, 380, 470, 'ygrb'],
  tools: [640, 600, 560, 650, 'yrg'], draft: [820, 600, 740, 650, 'yg'], mode: [962, 465, 990, 470, 'yg'],
  semi: [960, 320, 780, 300, 'y'], approval: [840, 200, 660, 170, 'yb'], sent: [840, 74, 660, 44, 'ygp'],
  auto: [1110, 330, 1130, 300, 'g'], security: [640, 380, 460, 350, 'r'], rejected: [500, 240, 320, 210, 'r'],
  archive: [580, 826, 500, 730, 'bp'], attach: [750, 820, 670, 730, 'b'], docs: [920, 826, 840, 730, 'bp'],
  people: [1090, 820, 1010, 730, 'b'], cal: [1330, 560, 1150, 530, 'b'], creds: [700, 902, 620, 930, 'p'],
  account: [850, 902, 790, 930, 'p'], encrypt: [1400, 700, 1420, 670, 'p']
};

// [name, card label, card line, text under the map]
const EN = {
  inbox: ['All your mailboxes', '01 / Arrival', 'Outlook, Gmail, Aruba, IMAP', 'A customer writes. GigaMail works with Microsoft 365 and any IMAP server: Outlook, Gmail, Aruba, Libero. Several accounts in one view, and each reply leaves from the right address.'],
  masker: ['Masker', '02 / Privacy', 'IBANs, phones hidden. No AI', 'In the desktop app, tax codes, VAT numbers, IBANs and phone numbers are replaced before a mail goes to the agent for a draft, and put back in the draft. Rules and checksums, no AI. For MCP agents it comes with the next release.'],
  llm: ['LLM', '03 / Understand', 'Context becomes a reply', 'Your agent brings the intelligence: Claude, Codex, OpenClaw, Hermes or your own. It reads the request and the context you allow. It can propose an action, never approve it.'],
  tools: ['Tools', '04 / Tool depot', 'Reads free, sends gated', 'Reading and searching are free. Sending, replying, deleting and calendar changes wait behind the approval gate. A hostile mail that pushes the agent to send stops here too.'],
  draft: ['Draft', '05 / Compose', 'Your figures, your tone', 'The reply uses your figures, your tone and real free slots, and stops where your documents stop. You can edit it before it goes.'],
  mode: ['Choose a lane', '06 / Routing', 'How much autonomy?', 'Semi-autopilot prepares a proposal and asks you each time. Autopilot sends only inside a rule you signed.'],
  semi: ['Semi-autopilot', '07 / Prepared', 'Prepared. Not sent.', 'The agent has done the work. The draft waits for you: nothing has been sent.'],
  approval: ['Approval', '08 / Your last word', 'Windows Hello, Touch ID, phone', 'You approve outside the agent’s reach: in the app, on your phone or from a notification, confirmed with Windows Hello or Touch ID. Calendar events are created only after this step.'],
  sent: ['Delivered', 'Outcome', 'Leaves exactly as you saw it', 'What leaves is exactly what you approved: same recipients, same attachments. Every send is written to the action log.'],
  auto: ['Autopilot', '07 / Your rule', 'Scope, expiry, daily cap', 'A rule you create for chosen senders and documents, with a scope, an expiry and a daily cap. No tool can switch one on. Anything outside the rule comes back to you.'],
  security: ['Injection lab', 'Security', 'A mail can’t rewrite rules', 'Mail content is untrusted input. Hidden text is left out and flagged, programs never reach the agent, and an instruction in a mail cannot add an account or approve a send.'],
  rejected: ['Rejected', 'Outcome', 'Nothing sent', 'Saying no is always safe: rejecting needs no confirmation and sends nothing.'],
  archive: ['Local archive', 'Context · Privacy', 'Every mail, on your PC', 'Every mail and attachment is kept in a local archive, even after the server drops it. “The quote we sent in March” is one question, and the answer comes from your own machine.'],
  attach: ['Reads attachments', 'Context', 'PDFs and office files', 'PDFs and office files are text to the agent, so the answer comes from the brochure, not from a guess.'],
  docs: ['Your documents', 'Context · Privacy', 'Only files you registered', 'Price lists, terms, product sheets. The agent can quote only the documents you registered: paths outside that list are refused.'],
  people: ['Remembers people', 'Context', 'History, tone, your notes', 'History, tone and your own notes sit next to each sender. Every draft to that person reads them first.'],
  cal: ['Books meetings', 'Context', 'Only your free slots', 'The agent offers only free slots inside your office hours. Microsoft 365 or Google Calendar.'],
  creds: ['Credentials', 'Privacy', 'No tool reads a password', 'Accounts are added by you, in the app or in your own shell. No tool lets an agent add an account or read a password, a token or a key.'],
  account: ['One account', 'Privacy', 'One mailbox per request', 'Every tool names the account it works on. An agent asking for one mailbox cannot read or write another.'],
  encrypt: ['Encrypted mail', 'Privacy · Beta', 'OpenPGP, end to end', 'In beta: new mail and replies can leave signed and encrypted with OpenPGP. A mail you asked to encrypt is never sent in clear.']
};
const IT = {
  inbox: ['Tutte le caselle', '01 / Arrivo', 'Outlook, Gmail, Aruba, IMAP', 'Un cliente scrive. GigaMail funziona con Microsoft 365 e con qualsiasi server IMAP: Outlook, Gmail, Aruba, Libero. Più account in una sola vista, e ogni risposta parte dall’indirizzo giusto.'],
  masker: ['Masker', '02 / Privacy', 'IBAN e telefoni nascosti', 'Nell’app desktop codici fiscali, partite IVA, IBAN e numeri di telefono vengono sostituiti prima che la mail arrivi all’agente per la bozza, e rimessi nella bozza. Regole e checksum, niente AI. Per gli agenti MCP arriva con la prossima release.'],
  llm: ['LLM', '03 / Capire', 'Il contesto diventa risposta', 'L’intelligenza la porta il tuo agente: Claude, Codex, OpenClaw, Hermes o il tuo. Legge la richiesta e il contesto che permetti. Può proporre un’azione, mai approvarla.'],
  tools: ['Strumenti', '04 / Deposito tools', 'Leggere sì, inviare no', 'Leggere e cercare sono liberi. Invii, risposte, cancellazioni e modifiche al calendario aspettano dietro il cancello dell’approvazione. Anche una mail ostile che spinge l’agente a inviare si ferma qui.'],
  draft: ['Bozza', '05 / Composizione', 'Le tue cifre, il tuo tono', 'La risposta usa le tue cifre, il tuo tono e orari liberi veri, e si ferma dove finiscono i tuoi documenti. Puoi modificarla prima che parta.'],
  mode: ['Scegli la corsia', '06 / Instradamento', 'Quanta autonomia?', 'Il semi-autopilot prepara una proposta e ti chiede ogni volta. L’autopilot invia solo dentro una regola che hai firmato.'],
  semi: ['Semi-autopilot', '07 / Preparata', 'Preparata. Non inviata.', 'L’agente ha fatto il lavoro. La bozza aspetta te: non è partito niente.'],
  approval: ['Approvazione', '08 / L’ultima parola', 'Windows Hello, Touch ID', 'Approvi fuori dalla portata dell’agente: nell’app, dal telefono o da una notifica, con Windows Hello o Touch ID. Gli eventi in calendario vengono creati solo dopo questo passaggio.'],
  sent: ['Consegnata', 'Esito', 'Parte com’è stata vista', 'Parte esattamente quello che hai approvato: stessi destinatari, stessi allegati. Ogni invio finisce nel registro delle azioni.'],
  auto: ['Autopilot', '07 / La tua regola', 'Ambito, scadenza, tetto', 'Una regola che crei tu per mittenti e documenti scelti, con un ambito, una scadenza e un tetto giornaliero. Nessuno strumento può attivarla. Tutto quello che esce dalla regola torna a te.'],
  security: ['Lab injection', 'Sicurezza', 'Una mail non cambia le regole', 'Il contenuto delle mail è input non fidato. Il testo nascosto viene tolto e segnalato, i programmi non arrivano all’agente, e un’istruzione in una mail non può aggiungere un account né approvare un invio.'],
  rejected: ['Rifiutata', 'Esito', 'Niente inviato', 'Dire no è sempre sicuro: il rifiuto non chiede conferme e non invia niente.'],
  archive: ['Archivio locale', 'Contesto · Privacy', 'Ogni mail, sul tuo PC', 'Ogni mail e ogni allegato restano in un archivio locale, anche dopo che il server li cancella. “Il preventivo che abbiamo mandato a marzo” è una domanda sola, e la risposta arriva dal tuo computer.'],
  attach: ['Legge gli allegati', 'Contesto', 'PDF e file Office', 'Per l’agente PDF e file Office sono testo: la risposta viene dalla brochure, non da un’ipotesi.'],
  docs: ['I tuoi documenti', 'Contesto · Privacy', 'Solo i file registrati', 'Listini, condizioni, schede prodotto. L’agente può citare solo i documenti che hai registrato: i percorsi fuori da quell’elenco vengono rifiutati.'],
  people: ['Ricorda le persone', 'Contesto', 'Storia, tono, tue note', 'Storia, tono e le tue note stanno accanto a ogni mittente. Ogni bozza per quella persona li legge prima.'],
  cal: ['Fissa appuntamenti', 'Contesto', 'Solo i tuoi orari liberi', 'L’agente propone solo orari liberi dentro il tuo orario d’ufficio. Microsoft 365 o Google Calendar.'],
  creds: ['Credenziali', 'Privacy', 'Nessun tool legge password', 'Gli account li aggiungi tu, nell’app o nella tua shell. Nessuno strumento permette all’agente di aggiungere un account o leggere una password, un token o una chiave.'],
  account: ['Un account', 'Privacy', 'Una casella per richiesta', 'Ogni strumento indica l’account su cui lavora. Un agente che chiede una casella non può leggerne o scriverne un’altra.'],
  encrypt: ['Mail cifrata', 'Privacy · Beta', 'OpenPGP, end to end', 'In beta: nuove mail e risposte possono partire firmate e cifrate con OpenPGP. Una mail che hai chiesto di cifrare non parte mai in chiaro.']
};
const TXT = it ? IT : EN;

const LINE = {
  y: { stops: ['inbox', 'masker', 'llm', 'tools', 'draft', 'mode', 'semi', 'approval', 'sent'], en: ['Answer a client', 'From the mail to your approval', 'semi-autopilot'], it: ['Rispondi a un cliente', 'Dalla mail alla tua approvazione', 'semi-autopilot'] },
  b: { stops: ['llm', 'archive', 'attach', 'docs', 'people', 'cal', 'approval'], en: ['Search my mail and files', 'Archive, attachments, documents, calendar', 'context'], it: ['Cerca nella posta e nei file', 'Archivio, allegati, documenti, calendario', 'contesto'] },
  p: { stops: ['inbox', 'masker', 'archive', 'creds', 'account', 'docs', 'encrypt', 'sent'], en: ['Keep my data private', 'On your machine, encrypted when you want', 'privacy'], it: ['Tieni privati i miei dati', 'Sul tuo computer, cifrati quando vuoi', 'privacy'] },
  g: { stops: ['inbox', 'llm', 'draft', 'mode', 'auto', 'sent'], en: ['Let it work alone', 'Autopilot inside your own rule', 'autopilot'], it: ['Lascialo lavorare da solo', 'Autopilot dentro la tua regola', 'autopilot'] },
  r: { stops: ['inbox', 'llm', 'tools', 'security', 'rejected'], en: ['Try to trick it', 'A hostile mail, stopped at the gate', 'untrusted input'], it: ['Prova a ingannarlo', 'Una mail ostile, fermata al cancello', 'input non fidato'] }
};
const ORDER = ['y', 'b', 'p', 'g', 'r'];
const T = it
  ? { next: 'prossima:', change: 'cambio per', end: 'fine corsa', all: ['Percorri tutte le linee', 'Il giro completo, circa due minuti'], pause: 'Pausa', play: 'Riprendi' }
  : { next: 'next:', change: 'change for', end: 'end of line', all: ['Ride every line', 'The whole tour, about two minutes'], pause: 'Pause', play: 'Play' };
const lname = l => LINE[l][it ? 'it' : 'en'];

const svg = $('mc-map'), frame = $('mc-frame'), stage = $('mc-stage');
const P = { y: $('Ly'), g: $('Lg'), r: $('Lr'), b: $('Lb'), p: $('Lp') };
const FULL = [-20, 20, 1640, 1000];

function nearest(p, x, y) {
  let best = 0, bd = Infinity; const len = p.getTotalLength();
  for (let l = 0; l <= len; l += 2) { const q = p.getPointAtLength(l), d = (q.x - x) ** 2 + (q.y - y) ** 2; if (d < bd) { bd = d; best = l; } }
  return best;
}
const POS = {};
for (const k in GEO) { POS[k] = {}; for (const l of GEO[k][4]) POS[k][l] = nearest(P[l], GEO[k][0], GEO[k][1]); }

// Stations, leader lines and cards.
const C = {}, LIFT = {};
function fit(t, max) { const w = t.getComputedTextLength(); if (w > max) t.setAttribute('font-size', (parseFloat(t.getAttribute('font-size')) * max / w).toFixed(2)); }
function build() {
  for (const k in GEO) {
    const [, , cx, cy, ls] = GEO[k], [name, label, short] = TXT[k];
    let x1 = Infinity, y1 = Infinity, x2 = -Infinity, y2 = -Infinity;
    for (const l of ls) { const q = P[l].getPointAtLength(POS[k][l]); x1 = Math.min(x1, q.x); y1 = Math.min(y1, q.y); x2 = Math.max(x2, q.x); y2 = Math.max(y2, q.y); }
    el('rect', { x: x1 - 12, y: y1 - 12, width: x2 - x1 + 24, height: y2 - y1 + 24, rx: 12, fill: '#fff', stroke: '#3d4836', 'stroke-width': 4 }, $('mc-stops'));
    el('line', { x1: (x1 + x2) / 2, y1: (y1 + y2) / 2, x2: cx + 80, y2: cy + 31, stroke: '#3d4836', 'stroke-width': 1.5, 'stroke-dasharray': '4 4' }, $('mc-leads'));
    const g = el('g', { tabindex: 0, role: 'button', 'aria-label': name }, $('mc-cards'));
    el('rect', { x: cx, y: cy, width: 160, height: 62, rx: 8, fill: '#fff', stroke: '#3d4836', 'stroke-width': 2 }, g);
    const w = 160 / ls.length;
    [...ls].forEach((l, i) => el('rect', { x: cx + i * w, y: cy, width: w, height: 6, fill: COL[l] }, g));
    const t = (s, yy, sz, wt, f) => { const e = el('text', { x: cx + 10, y: cy + yy, 'font-size': sz, 'font-weight': wt, fill: f, 'font-family': 'Poppins, Arial, sans-serif' }, g); e.textContent = s; fit(e, 140); };
    t(label.toUpperCase(), 22, 9, 500, '#8a7a5c'); t(name, 41, 15, 700, '#1d1d1b'); t(short, 55, 10, 400, '#5e5a4c');
    C[k] = g;
    const h = el('svg', { class: 'mc-lift', viewBox: `${cx - 2} ${cy - 2} 164 66`, width: 164, height: 66, 'aria-hidden': 'true' });
    const copy = g.cloneNode(true); copy.removeAttribute('tabindex'); copy.removeAttribute('role');
    h.appendChild(copy); h.style.display = 'none'; stage.appendChild(h); LIFT[k] = { el: h, v: 0, t: 0 };
    const open = () => { pause(); focusStation(k); };
    g.addEventListener('click', open);
    g.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(); } });
  }
}

// Text under the map.
function describe(k) {
  const [name, , , long] = TXT[k];
  $('mc-info-name').textContent = name;
  $('mc-info-lines').innerHTML = [...GEO[k][4]].map(l => `<span class="mc-chip"><i style="background:${COL[l]}"></i>${lname(l)[0]}</span>`).join('');
  $('mc-info-text').textContent = long;
}

// Choices and legend.
$('mc-legend').innerHTML = ORDER.map(l => `<div><span style="background:${COL[l]}"></span>${lname(l)[0]}</div>`).join('');
$('mc-choices').innerHTML = [...ORDER.map(l => [l, ...lname(l), COL[l]]), ['all', ...T.all, '', '#3d4836']]
  .map(o => `<button type="button" data-k="${o[0]}"><i style="background:${o[4]}"></i><span>${o[1]}<small>${o[2]}</small></span></button>`).join('');
$('mc-choices').querySelectorAll('button').forEach(b => b.addEventListener('click', () => begin(b.dataset.k)));

// Camera: the viewBox always matches the frame's shape.
let fw = 1, fh = 1;
function measure() { const r = frame.getBoundingClientRect(); fw = r.width; fh = r.height; }
let vb = [...FULL], tgt = [...FULL];
function zoomAt(x, y, s) { const w = fw / s, h = fh / s; tgt = [x - w / 2, y - h / 2, w, h]; }
function scaleFor() { return Math.min(1.35, fw / 420); }
function overviewBox() { const s = Math.min(fw / FULL[2], fh / FULL[3]); zoomAt(FULL[0] + FULL[2] / 2, FULL[1] + FULL[3] / 2, s * 0.97); }

let playing = false, tour = [], ti = 0, si = 0, phase = 'dwell', t0 = 0, from = 0, to = 0, typed = '', full = '', tick = 0;
function type(s) { full = s; typed = calm ? s : ''; if (calm) $('mc-next').textContent = s; }
function setLine(s) { $('mc-line').textContent = s; }
function show(k) { for (const c in LIFT) LIFT[c].t = c === k ? 1 : 0; }
function focusStation(k) {
  const [, , cx, cy] = GEO[k]; show(k); describe(k);
  zoomAt(cx + 80, cy + 31, scaleFor());
}
function lifts() {
  const M = svg.getScreenCTM(); if (!M) return;
  const f = frame.getBoundingClientRect(), pt = svg.createSVGPoint();
  for (const k in LIFT) {
    const o = LIFT[k];
    o.v = calm ? o.t : o.v + (o.t - o.v) * (o.t ? .12 : .18);
    if (o.v < .003 && !o.t) { if (o.el.style.display !== 'none') { o.el.style.display = 'none'; C[k].style.visibility = ''; } continue; }
    o.el.style.display = 'block'; C[k].style.visibility = 'hidden';
    pt.x = GEO[k][2] - 2; pt.y = GEO[k][3] - 2;
    const m = pt.matrixTransform(M), s = M.a, v = o.v, grow = 1 + .5 * v;
    o.el.style.zIndex = Math.round(v * 100);
    o.el.style.transform = `translate(${m.x - f.left}px,${m.y - f.top}px) translate(${82 * s}px,${33 * s}px) translateY(${-14 * v}px) rotateX(${10 * v}deg) scale(${s * grow}) translate(-82px,-33px)`;
    o.el.style.filter = `drop-shadow(0 ${(4 + 16 * v) / (s * grow)}px ${(4 + 14 * v) / (s * grow)}px rgba(58,46,26,${.12 + .25 * v}))`;
  }
}
function begin(k) {
  tour = k === 'all' ? [...ORDER] : [k];
  ti = 0; si = 0; phase = 'dwell'; t0 = 0; playing = true;
  $('mc-start').hidden = true; $('mc-ticker').hidden = false; $('mc-legend').classList.remove('on');
  setLine('gigamail · ' + lname(tour[0])[2]); type(TXT[LINE[tour[0]].stops[0]][0]); setPlay();
}
function step(ts) {
  requestAnimationFrame(step);
  const a = calm ? 1 : .06;
  for (let i = 0; i < 4; i++) vb[i] += (tgt[i] - vb[i]) * a;
  svg.setAttribute('viewBox', vb.map(n => n.toFixed(2)).join(' '));
  lifts();
  if (++tick % 3 === 0 && typed.length < full.length) { typed = full.slice(0, typed.length + 1); $('mc-next').textContent = typed; }
  if (!playing || ti >= tour.length) return;
  const ln = tour[ti], st = LINE[ln].stops, p = P[ln];
  if (!t0) t0 = ts; const e = ts - t0;
  if (phase === 'dwell') {
    const k = st[si], q = p.getPointAtLength(POS[k][ln]);
    $('mc-train').setAttribute('transform', `translate(${q.x},${q.y})`);
    if (e < 50) {
      const other = [...GEO[k][4]].filter(l => l !== ln);
      setLine(other.length ? T.change + ' ' + other.map(l => lname(l)[2]).join(', ') : 'gigamail · ' + lname(ln)[2]);
      show(k); describe(k);
      zoomAt((q.x + GEO[k][2] + 80) / 2, (q.y + GEO[k][3] + 31) / 2, scaleFor());
    }
    if (e > (calm ? 4200 : 2300)) {
      setLine('gigamail · ' + lname(ln)[2]);
      if (si + 1 < st.length) { from = POS[k][ln]; const n = st[si + 1]; to = POS[n][ln]; type(TXT[n][0]); phase = 'move'; t0 = ts; show(null); }
      else { ti++; si = 0; t0 = ts; if (ti < tour.length) { setLine('gigamail · ' + lname(tour[ti])[2]); type(TXT[LINE[tour[ti]].stops[0]][0]); } else end(); }
    }
  } else {
    const dur = calm ? 1 : Math.max(800, Math.abs(to - from) * 3.8), u = Math.min(1, e / dur);
    const ease = u < .5 ? 2 * u * u : 1 - (-2 * u + 2) ** 2 / 2, l = from + (to - from) * ease;
    const q = p.getPointAtLength(l), q2 = p.getPointAtLength(Math.min(l + 1, p.getTotalLength()));
    $('mc-train').setAttribute('transform', `translate(${q.x},${q.y}) rotate(${(Math.atan2(q2.y - q.y, q2.x - q.x) * 180 / Math.PI).toFixed(1)})`);
    zoomAt(q.x, q.y, scaleFor() * 1.12);
    if (u >= 1) { si++; phase = 'dwell'; t0 = ts; }
  }
}
function overview() { overviewBox(); show(null); $('mc-legend').classList.add('on'); }
function end() { overview(); type(T.end); playing = false; setPlay(); }
function pause() { playing = false; setPlay(); }
function setPlay() {
  const b = $('mc-play'); b.setAttribute('aria-label', playing ? T.pause : T.play);
  b.innerHTML = playing ? '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 5h4v14H7zM13 5h4v14h-4z"/></svg>' : '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 4l13 8-13 8z"/></svg>';
}
function menu() { pause(); overview(); $('mc-start').hidden = false; $('mc-start').querySelector('button').focus({ preventScroll: true }); }
$('mc-play').addEventListener('click', () => { if (!tour.length || ti >= tour.length) return menu(); playing = !playing; t0 = 0; setPlay(); });
$('mc-lines').addEventListener('click', menu);
$('mc-overview').addEventListener('click', () => { pause(); $('mc-start').hidden = true; overview(); });
addEventListener('resize', () => { measure(); if (!playing) overviewBox(); });

(document.fonts ? document.fonts.ready : Promise.resolve()).then(() => {
  measure(); build(); overviewBox(); vb = [...tgt];
  $('mc-train').setAttribute('transform', 'translate(100,600)');
  setPlay(); requestAnimationFrame(step);
});
