// Email checker for gigamail.ai/email-check.html: phishing signals and text
// hidden from the reader but not from an AI agent. Everything runs in the
// visitor's browser: the pasted mail is never sent anywhere.
//
// The parsing and the rules are plain functions (tested with Node in
// tests/test_site_email_check.py); finding hidden text needs a browser, so
// findHiddenText renders the mail in a sandboxed iframe with no scripts and
// no network, and asks the layout what a reader would see.

// ---- MIME ------------------------------------------------------------------

const HEADER_HINT = /^(received|return-path|from|to|subject|date|mime-version|content-type|message-id|delivered-to|authentication-results):/im;

export function looksLikeRawEmail(text) {
  const head = String(text || '').split(/\r?\n\r?\n/, 1)[0];
  const hits = head.split(/\r?\n/).filter(l => HEADER_HINT.test(l)).length;
  return hits >= 2;
}

function splitHeadBody(raw) {
  const m = /\r?\n\r?\n/.exec(raw);
  if (!m) return [raw, ''];
  return [raw.slice(0, m.index), raw.slice(m.index + m[0].length)];
}

export function parseHeaders(block) {
  const out = [];
  for (const line of String(block).split(/\r?\n/)) {
    if (/^[ \t]/.test(line) && out.length) out[out.length - 1][1] += ' ' + line.trim();
    else {
      const i = line.indexOf(':');
      if (i > 0) out.push([line.slice(0, i).trim().toLowerCase(), line.slice(i + 1).trim()]);
    }
  }
  return out;
}

const header = (hs, name) => (hs.find(h => h[0] === name) || [, ''])[1];
const headersAll = (hs, name) => hs.filter(h => h[0] === name).map(h => h[1]);

function param(value, name) {
  const m = new RegExp(name + '\\s*=\\s*("([^"]*)"|[^;\\s]+)', 'i').exec(value || '');
  return m ? (m[2] !== undefined ? m[2] : m[1]) : '';
}

function bytesFromBinaryString(s) {
  const b = new Uint8Array(s.length);
  for (let i = 0; i < s.length; i++) b[i] = s.charCodeAt(i) & 0xff;
  return b;
}

function decodeBytes(bytes, charset) {
  try { return new TextDecoder(charset || 'utf-8', { fatal: false }).decode(bytes); }
  catch { return new TextDecoder('utf-8').decode(bytes); }
}

export function decodeTransfer(body, encoding, charset) {
  const enc = String(encoding || '').toLowerCase();
  if (enc === 'base64') {
    try { return decodeBytes(bytesFromBinaryString(atob(body.replace(/[^A-Za-z0-9+/=]/g, ''))), charset); }
    catch { return body; }
  }
  if (enc === 'quoted-printable') {
    const s = body.replace(/=\r?\n/g, '').replace(/=([0-9A-Fa-f]{2})/g, (_, h) => String.fromCharCode(parseInt(h, 16)));
    return decodeBytes(bytesFromBinaryString(s), charset);
  }
  return body;
}

// An attachment's bytes, as sent.
export function decodeBinary(body, encoding) {
  const enc = String(encoding || '').toLowerCase();
  if (enc === 'base64') {
    try { return bytesFromBinaryString(atob(body.replace(/[^A-Za-z0-9+/=]/g, ''))); } catch { return new Uint8Array(); }
  }
  if (enc === 'quoted-printable') {
    return bytesFromBinaryString(body.replace(/=\r?\n/g, '').replace(/=([0-9A-Fa-f]{2})/g, (_, h) => String.fromCharCode(parseInt(h, 16))));
  }
  return new TextEncoder().encode(body);
}

// Decodes RFC 2047 encoded words (=?utf-8?B?...?=) in a header value.
export function decodeWords(value) {
  return String(value || '').replace(/=\?([^?]+)\?([bBqQ])\?([^?]*)\?=/g, (_, cs, kind, text) => {
    try {
      const s = kind.toUpperCase() === 'B' ? atob(text)
        : text.replace(/_/g, ' ').replace(/=([0-9A-Fa-f]{2})/g, (__, h) => String.fromCharCode(parseInt(h, 16)));
      return decodeBytes(bytesFromBinaryString(s), cs);
    } catch { return text; }
  });
}

function walkPart(head, body, acc, depth) {
  const hs = parseHeaders(head);
  const ctype = header(hs, 'content-type') || 'text/plain';
  const type = ctype.split(';')[0].trim().toLowerCase();
  const disp = header(hs, 'content-disposition');
  const name = decodeWords(param(disp, 'filename') || param(ctype, 'name'));
  if (type.startsWith('multipart/') && depth < 8) {
    const boundary = param(ctype, 'boundary');
    if (!boundary) return;
    const pieces = body.split('--' + boundary);
    for (const piece of pieces.slice(1)) {
      if (piece.startsWith('--')) break;
      const [h, b] = splitHeadBody(piece.replace(/^\r?\n/, ''));
      walkPart(h, b, acc, depth + 1);
    }
    return;
  }
  if (name || /attachment/i.test(disp)) {
    acc.attachments.push({ name: name || '(unnamed)', type, bytes: decodeBinary(body, header(hs, 'content-transfer-encoding')) });
    return;
  }
  const text = decodeTransfer(body, header(hs, 'content-transfer-encoding'), param(ctype, 'charset'));
  if (type === 'text/html' && !acc.html) acc.html = text;
  else if (type === 'text/plain' && !acc.plain) acc.plain = text;
}

// What the visitor pasted: a raw message (headers and MIME parts), HTML,
// or plain text.
export function parseInput(input) {
  const text = String(input || '').trim();
  const out = { raw: false, headers: [], html: '', plain: '', attachments: [] };
  if (looksLikeRawEmail(text)) {
    out.raw = true;
    const [head, body] = splitHeadBody(text);
    out.headers = parseHeaders(head);
    walkPart(head, body, out, 0);
  } else if (/<(html|body|div|p|span|table|td|a|font|br)\b/i.test(text)) {
    out.html = text;
  } else {
    out.plain = text;
  }
  return out;
}

// ---- Addresses and links ---------------------------------------------------

export function addressOf(value) {
  const v = decodeWords(value);
  const m = /<([^>]+)>/.exec(v) || /([^\s<>"]+@[^\s<>"]+)/.exec(v);
  const address = m ? m[1].trim().toLowerCase() : '';
  const name = v.replace(/<[^>]*>/, '').replace(/"/g, '').trim();
  return { name, address, domain: address.includes('@') ? address.split('@').pop() : '' };
}

// The registrable part of a host, good enough to compare two domains:
// mail.example.co.uk and example.co.uk give the same answer.
export function baseDomain(host) {
  const parts = String(host || '').toLowerCase().replace(/\.$/, '').split('.').filter(Boolean);
  if (parts.length <= 2) return parts.join('.');
  const second = parts[parts.length - 2];
  const two = ['co', 'com', 'org', 'net', 'gov', 'ac', 'edu'].includes(second) && parts[parts.length - 1].length === 2;
  return parts.slice(two ? -3 : -2).join('.');
}

export function hostOf(url) {
  try { return new URL(url).hostname.toLowerCase(); } catch { return ''; }
}

const SHORTENERS = new Set(['bit.ly', 'tinyurl.com', 't.co', 'goo.gl', 'is.gd', 'ow.ly', 'rebrand.ly', 'cutt.ly', 'buff.ly', 'shorturl.at', 'tiny.cc', 'rb.gy']);

// ---- Look-alike domains ----------------------------------------------------

// The brands phishing imitates most, with the domains they really send from
// and link to. A domain that reads like one of them and is not one of them
// is a look-alike.
const BRANDS = {
  paypal: ['paypal.com', 'paypal.me', 'paypalobjects.com', 'paypal-community.com'],
  microsoft: ['microsoft.com', 'microsoftonline.com', 'office.com', 'office365.com', 'live.com', 'outlook.com', 'hotmail.com', 'sharepoint.com', 'onmicrosoft.com', 'azure.com', 'windows.com', 'msn.com', 'bing.com', 'skype.com', 'microsoft365.com', 'cloud.microsoft'],
  apple: ['apple.com', 'icloud.com', 'me.com', 'mac.com', 'apple.news'],
  icloud: ['icloud.com', 'apple.com'],
  amazon: ['amazon.com', 'amazon.it', 'amazon.de', 'amazon.co.uk', 'amazon.fr', 'amazon.es', 'amazon.ca', 'amazon.com.au', 'amazon.co.jp', 'amazon.in', 'amazon.nl', 'amazonaws.com', 'amazonses.com', 'a2z.com', 'amazon.jobs', 'primevideo.com', 'amazonpay.com'],
  google: ['google.com', 'google.it', 'google.co.uk', 'google.de', 'google.fr', 'gmail.com', 'googlemail.com', 'googleusercontent.com', 'googleapis.com', 'g.co', 'goo.gl', 'youtube.com', 'gstatic.com', 'withgoogle.com'],
  gmail: ['gmail.com', 'google.com', 'googlemail.com'],
  netflix: ['netflix.com', 'nflxext.com', 'nflximg.net'],
  facebook: ['facebook.com', 'fb.com', 'facebookmail.com', 'meta.com', 'fb.me'],
  instagram: ['instagram.com', 'facebookmail.com', 'meta.com'],
  whatsapp: ['whatsapp.com', 'whatsapp.net', 'wa.me', 'meta.com'],
  linkedin: ['linkedin.com', 'lnkd.in', 'licdn.com'],
  docusign: ['docusign.com', 'docusign.net'],
  dropbox: ['dropbox.com', 'dropboxmail.com', 'db.tt'],
  adobe: ['adobe.com', 'adobesign.com', 'acrobat.com', 'adobelogin.com'],
  coinbase: ['coinbase.com'],
  binance: ['binance.com'],
  chase: ['chase.com', 'jpmorganchase.com'],
  wellsfargo: ['wellsfargo.com', 'wf.com'],
  bankofamerica: ['bankofamerica.com', 'bofa.com'],
  dhl: ['dhl.com', 'dhl.it', 'dhl.de', 'dhl.co.uk', 'dhl.fr', 'dhl.es'],
  fedex: ['fedex.com'],
  ups: ['ups.com'],
  usps: ['usps.com'],
  irs: ['irs.gov'],
  poste: ['poste.it', 'posteitaliane.it', 'postepay.it'],
  posteitaliane: ['poste.it', 'posteitaliane.it'],
  intesasanpaolo: ['intesasanpaolo.com', 'intesasanpaolo.it'],
  unicredit: ['unicredit.it', 'unicredit.eu', 'unicreditgroup.eu'],
  agenziaentrate: ['agenziaentrate.gov.it', 'agenziaentrateriscossione.gov.it'],
};

const WORDY = new Set(['apple', 'chase', 'ups', 'usps', 'irs', 'dhl', 'poste', 'adobe', 'office']);

// Words scammers glue to a brand: "paypalsecure", "microsoft-login".
const BAIT = ['secure', 'security', 'login', 'signin', 'verify', 'verification', 'account', 'accounts', 'support', 'service', 'services', 'update', 'help', 'billing', 'team', 'online', 'auth', 'id', 'wallet', 'alert', 'alerts', 'notice', 'mail', 'center', 'confirm', 'helpdesk', 'it', 'us', 'web'];

function deobfuscate(s) {
  return s.replace(/rn/g, 'm').replace(/vv/g, 'w').replace(/0/g, 'o').replace(/1/g, 'l').replace(/3/g, 'e')
    .replace(/4/g, 'a').replace(/5/g, 's').replace(/7/g, 't').replace(/8/g, 'b');
}

function editDistance(a, b) {
  if (Math.abs(a.length - b.length) > 1) return 2;
  const prev = Array.from({ length: b.length + 1 }, (_, i) => i);
  for (let i = 1; i <= a.length; i++) {
    let diag = prev[0];
    prev[0] = i;
    for (let j = 1; j <= b.length; j++) {
      const keep = prev[j];
      prev[j] = Math.min(prev[j] + 1, prev[j - 1] + 1, diag + (a[i - 1] === b[j - 1] ? 0 : 1));
      diag = keep;
    }
  }
  return prev[b.length];
}

function tokenNamesBrand(token, brand) {
  if (token === brand) return true;
  if (brand.length >= 6 && editDistance(token, brand) === 1) return true;
  if (token.startsWith(brand) && BAIT.includes(token.slice(brand.length))) return true;
  if (token.endsWith(brand) && BAIT.includes(token.slice(0, -brand.length))) return true;
  return false;
}

function isBrandDomain(host, brand) {
  const h = String(host).toLowerCase();
  if (BRANDS[brand].some(d => h === d || h.endsWith('.' + d))) return true;
  // The brand's own name on a country domain (amazon.com.br, google.es):
  // the big brands hold those, and listing them all is not possible.
  const base = baseDomain(h).split('.');
  return base[0] === brand && base[base.length - 1].length === 2;
}

// The brand a host imitates, or ''. "paypal.com.example.net",
// "paypa1-secure.com" and "micros0ft.com" all name a brand they are not.
export function lookalike(host, top) {
  const h = String(host || '').toLowerCase().replace(/\.$/, '');
  if (!h || /^\d{1,3}(\.\d{1,3}){3}$/.test(h)) return '';
  if (top && top.set.has(baseDomain(h))) return '';   // a popular site is not a look-alike
  const split = labels => labels.flatMap(l => [l, ...l.split('-')]).map(deobfuscate).filter(Boolean);
  const base = baseDomain(h);
  const own = split(base.split('.').slice(0, 1));            // the name the domain was registered as
  const all = split(h.split('.').slice(0, -1));               // with every subdomain
  for (const brand of Object.keys(BRANDS)) {
    if (isBrandDomain(h, brand)) continue;
    // Brands that are also everyday words (apple, chase, ups...) count only
    // in the registered name: "apple.example.edu" is a server, not a scam.
    const tokens = WORDY.has(brand) ? own : all;
    if (tokens.some(t => tokenNamesBrand(t, brand))) return brand;
  }
  return '';
}

// A display name that claims a brand the address does not belong to:
// "PayPal" <service@example.net>.
export function brandInName(name, domain) {
  const words = String(name || '').toLowerCase().split(/[^a-z0-9]+/).filter(Boolean);
  for (const brand of Object.keys(BRANDS)) {
    if (brand.length < 4) continue;
    if (words.includes(brand) && domain && !isBrandDomain(domain, brand)) return brand;
  }
  return '';
}

// ---- Popular sites and known bad hosts ----------------------------------------
//
// Both lists are rebuilt every day from public sources by
// scripts/build_checker_lists.py and published on the checker-data branch.
// The page downloads the popular list, and of the bad list only the shards
// (1/256 each) of the hosts in the mail it checks: no host name leaves the
// browser.

export const DATA_URL = 'https://raw.githubusercontent.com/adecubed/gigamail/checker-data/';

// The ranking, as {set, labels, near}: `labels` maps a registered name
// ("paypal") to its domain; `near` holds the names of the top 1,000, for
// one-letter typos.
export function parseTop(text) {
  const domains = String(text || '').split(/\s+/).filter(Boolean);
  const labels = new Map(), near = [];
  domains.forEach((d, i) => {
    const label = baseDomain(d).split('.')[0];
    if (label.length < 5 || labels.has(label)) return;
    labels.set(label, d);
    if (i < 1000 && label.length >= 7) near.push(label);
  });
  return { set: new Set(domains), labels, near };
}

// A popular site this host imitates, or ''. Only the registered name is
// compared: "paypa1.com" against "paypal", "amazom.co" against "amazon".
export function popularLookalike(host, top) {
  if (!top) return { domain: '', level: '' };
  const base = baseDomain(host);
  if (!base || top.set.has(base) || /^\d+(\.\d+){3}$/.test(base)) return { domain: '', level: '' };
  const label = base.split('.')[0];
  const plain = deobfuscate(label);
  if (plain !== label && label.length >= 5 && top.labels.has(plain)) return { domain: top.labels.get(plain), level: 'high' };
  if (label.length >= 7) {
    const hit = top.near.find(n => n !== label && editDistance(label, n) === 1);
    if (hit) return { domain: top.labels.get(hit), level: 'medium' };
  }
  return { domain: '', level: '' };
}

// The names worth looking up for a host: itself and its parents down to
// the registered domain (a.b.example.com, b.example.com, example.com).
export function hostsToCheck(host) {
  const h = String(host || '').toLowerCase().replace(/\.$/, '');
  if (!h) return [];
  if (/^\d{1,3}(\.\d{1,3}){3}$/.test(h)) return [h];
  const base = baseDomain(h);
  const parts = h.split('.');
  const out = [];
  for (let i = 0; i < parts.length; i++) {
    const name = parts.slice(i).join('.');
    out.push(name);
    if (name === base) break;
  }
  return out;
}

export async function sha256(text) {
  return new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text)));
}

// Whether a shard holds a host's hash: rows of 9 bytes (hash bytes 1-8 and
// a flag), sorted. Returns the flag, 0 when absent.
export function findInShard(shard, digest) {
  let lo = 0, hi = Math.floor(shard.length / 9) - 1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    let cmp = 0;
    for (let k = 0; k < 8 && !cmp; k++) cmp = shard[mid * 9 + k] - digest[k + 1];
    if (!cmp) return shard[mid * 9 + 8];
    if (cmp < 0) lo = mid + 1; else hi = mid - 1;
  }
  return 0;
}

// Hosts found on the bad lists: Map host -> 'phishing' | 'malware'.
// `getShard(hex)` returns a shard's bytes.
export async function knownBad(hosts, getShard) {
  const found = new Map();
  const names = [...new Set(hosts.flatMap(hostsToCheck))];
  const digests = await Promise.all(names.map(sha256));
  const shards = new Map();
  for (const d of digests) {
    const hex = d[0].toString(16).padStart(2, '0');
    if (!shards.has(hex)) shards.set(hex, getShard(hex));
  }
  const loaded = await Promise.all([...shards.values()]);  // one failure fails the lookup, none left unhandled
  [...shards.keys()].forEach((hex, i) => shards.set(hex, loaded[i]));
  names.forEach((name, i) => {
    const d = digests[i];
    const flag = findInShard(shards.get(d[0].toString(16).padStart(2, '0')), d);
    if (flag) found.set(name, flag & 1 ? 'phishing' : 'malware');
  });
  return found;
}

// Every host a mail names: sender, Reply-To, bounce address and links.
export function hostsOf(parsed, links) {
  const hs = parsed.headers || [];
  const out = ['from', 'reply-to', 'return-path', 'sender'].map(n => addressOf(header(hs, n)).domain);
  for (const l of links) out.push(hostOf(l.href));
  return [...new Set(out.filter(Boolean))];
}

// One finding per suspicious link. `text` is what the reader sees.
export function checkLink(href, text, top) {
  const out = [];
  const h = String(href || '').trim();
  if (/^(javascript|data|vbscript):/i.test(h)) {
    out.push({ level: 'high', id: 'script-link', detail: h.slice(0, 80) });
    return out;
  }
  const host = hostOf(h);
  if (!host) return out;
  if (/^\d{1,3}(\.\d{1,3}){3}$/.test(host)) out.push({ level: 'high', id: 'ip-link', detail: host });
  if (host.split('.').some(p => p.startsWith('xn--'))) out.push({ level: 'high', id: 'punycode', detail: host });
  if (SHORTENERS.has(host)) out.push({ level: 'medium', id: 'shortener', detail: host });
  const imitates = lookalike(host, top);
  if (imitates) out.push({ level: 'high', id: 'lookalike-link', detail: `${host} (${imitates}?)` });
  else {
    const pop = popularLookalike(host, top);
    if (pop.domain) out.push({ level: pop.level, id: 'lookalike-link', detail: `${host} (${pop.domain}?)` });
  }
  const shown = String(text || '').trim();
  const shownHost = /^(https?:\/\/)?([a-z0-9-]+\.)+[a-z]{2,}(\/\S*)?$/i.test(shown)
    ? hostOf(/^https?:/i.test(shown) ? shown : 'https://' + shown) : '';
  if (shownHost && baseDomain(shownHost) !== baseDomain(host)) {
    out.push({ level: 'high', id: 'link-mismatch', detail: `${shownHost} → ${host}` });
  }
  return out;
}

// ---- Words -----------------------------------------------------------------

// Pressure and credential words (English and Italian).
const PRESSURE = [
  /verify your (account|identity|details)/i, /(account|mailbox) (has been |will be )?(suspended|locked|disabled|closed)/i,
  /unusual (sign-?in|activity|login)/i, /within (24|48) hours/i, /(confirm|update) your (payment|billing|details|password)/i,
  /gift ?cards?/i, /wire transfer/i, /(urgent|immediately|final notice|last warning)/i, /your password (expires|has expired)/i,
  /verifica (il tuo|i tuoi) (account|dati)/i, /account (sospeso|bloccato)/i, /entro (24|48) ore/i, /(conferma|aggiorna) i tuoi dati/i,
  /bonifico (urgente|immediato)/i, /carta regalo/i,
];

// Words addressed to an AI that reads the mail, not to a person.
const AGENT = [
  /ignore (all |any )?(previous|prior|above|earlier) (instructions|messages|rules)/i,
  /\b(AI|LLM) (assistant|agent|model)\b/i, /\bas an AI\b/i, /\byou are (an? )?(AI|assistant|agent|language model)/i,
  /system prompt/i, /do not (tell|inform|mention|alert|notify) (the )?(user|recipient|human)/i,
  /\bforward (all|every|the|any|this)\b/i, /delete (this|the) (email|message|mail)/i,
  /password reset/i, /\bassistant:/i, /<\/?(instructions|system)>/i,
  /ignora (tutte )?le istruzioni (precedenti)?/i, /inoltra (tutte|ogni|questa)/i, /non (dirlo|dire nulla) all'utente/i,
];

export function pressureSignals(text) {
  return PRESSURE.filter(r => r.test(text || '')).map(r => (text.match(r) || [''])[0]);
}

export function agentSignals(text) {
  return AGENT.filter(r => r.test(text || '')).map(r => (text.match(r) || [''])[0]);
}

const INVISIBLE = /[​-‍⁠﻿‪-‮⁦-⁩­]/g;

export function invisibleCharacters(text) {
  return (String(text || '').match(INVISIBLE) || []).length;
}


// ---- Headers ---------------------------------------------------------------

export function headerSignals(headers, top) {
  const out = [];
  if (!headers || !headers.length) return out;
  const from = addressOf(header(headers, 'from'));
  const reply = addressOf(header(headers, 'reply-to'));
  const ret = addressOf(header(headers, 'return-path'));
  if (reply.domain && from.domain && baseDomain(reply.domain) !== baseDomain(from.domain)) {
    out.push({ level: 'high', id: 'reply-to', detail: `${from.domain} → ${reply.domain}` });
  }
  if (ret.domain && from.domain && baseDomain(ret.domain) !== baseDomain(from.domain)) {
    out.push({ level: 'low', id: 'return-path', detail: `${from.domain} → ${ret.domain}` });
  }
  const shownAddr = /[^\s<>"]+@[^\s<>"]+\.[a-z]{2,}/i.exec(from.name || '');
  if (shownAddr && from.domain && baseDomain(shownAddr[0].split('@').pop()) !== baseDomain(from.domain)) {
    out.push({ level: 'high', id: 'display-name', detail: `${shownAddr[0]} → ${from.address}` });
  }
  for (const [who, addr] of [['from', from], ['reply-to', reply]]) {
    const imitates = lookalike(addr.domain, top);
    if (imitates) { out.push({ level: 'high', id: 'lookalike-sender', detail: `${who}: ${addr.domain} (${imitates}?)` }); continue; }
    const pop = popularLookalike(addr.domain, top);
    if (pop.domain) out.push({ level: pop.level, id: 'lookalike-sender', detail: `${who}: ${addr.domain} (${pop.domain}?)` });
  }
  const claimed = brandInName(from.name, from.domain);
  if (claimed) out.push({ level: 'medium', id: 'brand-name', detail: `"${from.name}" <${from.address}>` });
  const auth = headersAll(headers, 'authentication-results').join(' ; ').toLowerCase();
  for (const check of ['spf', 'dkim', 'dmarc']) {
    const m = new RegExp(check + '=(\\w+)').exec(auth);
    if (m && ['fail', 'softfail', 'permerror', 'none'].includes(m[1])) {
      out.push({ level: m[1] === 'none' || m[1] === 'softfail' ? 'medium' : 'high', id: check, detail: `${check}=${m[1]}` });
    }
  }
  return out;
}

// ---- Verdict ---------------------------------------------------------------

export function verdict(findings) {
  const high = findings.filter(f => f.level === 'high').length;
  const medium = findings.filter(f => f.level === 'medium').length;
  if (high) return 'danger';
  if (medium) return 'warning';
  return 'clean';
}

// Everything that does not need a browser. `hidden` comes from
// findHiddenText (or is empty when there is no HTML).
// `intel` (optional): {top: parseTop(...), bad: knownBad(...)}.
export function analyse(parsed, hidden, visibleText, links, reports, intel) {
  const top = intel && intel.top;
  const findings = [];
  for (const [host, kind] of (intel && intel.bad) || []) {
    findings.push({ level: 'high', id: 'known-bad', detail: `${host} (${kind})` });
  }
  findings.push(...headerSignals(parsed.headers, top));
  for (const l of links) findings.push(...checkLink(l.href, l.text, top));
  const hiddenText = hidden.map(h => h.text).join('\n');
  if (hidden.length) {
    // Newsletters hide a short preview line as a matter of course: alone, a
    // little hidden text is worth showing, not worth a warning.
    const said = agentSignals(hiddenText);
    const level = said.length ? 'high' : hiddenText.length > 200 ? 'medium' : 'low';
    findings.push({ level, id: said.length ? 'hidden-instructions' : 'hidden-text', detail: said.join(', ') });
  }
  const shownAgent = agentSignals(visibleText);
  if (shownAgent.length) findings.push({ level: 'medium', id: 'visible-instructions', detail: shownAgent.join(', ') });
  const pressure = pressureSignals(visibleText);
  if (pressure.length) findings.push({ level: 'medium', id: 'pressure', detail: pressure.join(', ') });
  const zw = invisibleCharacters(visibleText + hiddenText);
  if (zw >= 5) findings.push({ level: 'medium', id: 'invisible-chars', detail: String(zw) });
  for (const report of reports || []) findings.push(...report.findings.map(f => ({ ...f, file: report.name })));
  return { findings, verdict: verdict(findings) };
}

// Links in plain text: what is shown is the link itself.
export function plainLinks(text) {
  return (String(text || '').match(/https?:\/\/[^\s<>"')]+/g) || []).map(u => ({ href: u, text: u }));
}

// ---- Attachments -----------------------------------------------------------

const EXEC_EXT = /\.(exe|scr|com|pif|bat|cmd|msi|msix|appx|jar|js|jse|vbs|vbe|wsf|wsh|hta|ps1|lnk|reg|cpl|dll|iso|img|vhd|vhdx|one|xll|chm|url|application|gadget|apk|dmg|pkg|sh|command)$/i;
const SCRIPT_PAGE_EXT = /\.(html?|shtml|xhtml|svg|mht|mhtml)$/i;
const MACRO_EXT = /\.(docm|dotm|xlsm|xltm|xlam|pptm|potm|ppsm|sldm)$/i;
const ARCHIVE_EXT = /\.(zip|rar|7z|tar|gz|tgz|bz2|xz|cab|arj|ace|z)$/i;
const DOC_EXT = /\.(pdf|docx?|xlsx?|pptx?|txt|csv|rtf|odt|ods|jpe?g|png|gif|heic)$/i;

function startsWith(bytes, ...sig) {
  return sig.every((b, i) => bytes[i] === b);
}

// What the bytes actually are, whatever the name says.
export function sniff(bytes) {
  if (!bytes || bytes.length < 4) return '';
  if (startsWith(bytes, 0x4d, 0x5a)) return 'program (Windows .exe)';
  if (startsWith(bytes, 0x7f, 0x45, 0x4c, 0x46)) return 'program (Linux)';
  if (startsWith(bytes, 0xcf, 0xfa, 0xed, 0xfe) || startsWith(bytes, 0xca, 0xfe, 0xba, 0xbe)) return 'program (macOS)';
  if (startsWith(bytes, 0x25, 0x50, 0x44, 0x46)) return 'pdf';
  if (startsWith(bytes, 0x50, 0x4b, 0x03, 0x04) || startsWith(bytes, 0x50, 0x4b, 0x05, 0x06)) return 'zip';
  if (startsWith(bytes, 0x52, 0x61, 0x72, 0x21)) return 'rar';
  if (startsWith(bytes, 0x37, 0x7a, 0xbc, 0xaf)) return '7z';
  if (startsWith(bytes, 0xd0, 0xcf, 0x11, 0xe0)) return 'office (old format)';
  if (startsWith(bytes, 0xff, 0xd8, 0xff)) return 'jpeg';
  if (startsWith(bytes, 0x89, 0x50, 0x4e, 0x47)) return 'png';
  if (startsWith(bytes, 0x47, 0x49, 0x46, 0x38)) return 'gif';
  if (bytes.length > 0x8006 && String.fromCharCode(...bytes.slice(0x8001, 0x8006)) === 'CD001') return 'disk image (ISO)';
  const head = new TextDecoder('latin1').decode(bytes.slice(0, 512)).replace(/^﻿/, '').trimStart().toLowerCase();
  if (/^(<!doctype html|<html|<head|<body|<script|<meta|<form|<iframe)/.test(head)) return 'web page (html)';
  if (/^(<\?xml[^>]*>\s*)?<svg/.test(head)) return 'svg';
  return '';
}

const EXPECT = { pdf: 'pdf', zip: 'zip', docx: 'zip', xlsx: 'zip', pptx: 'zip', docm: 'zip', xlsm: 'zip', pptm: 'zip', odt: 'zip', ods: 'zip', jpg: 'jpeg', jpeg: 'jpeg', png: 'png', gif: 'gif', doc: 'office (old format)', xls: 'office (old format)', ppt: 'office (old format)', rar: 'rar', '7z': '7z' };

// Entries of a zip (docx, xlsx and pptx are zips too), read from the central
// directory. `read(entry)` inflates one entry when the browser can.
export function zipEntries(bytes) {
  const dv = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  let eocd = -1;
  for (let i = bytes.length - 22; i >= Math.max(0, bytes.length - 65557); i--) {
    if (dv.getUint32(i, true) === 0x06054b50) { eocd = i; break; }
  }
  if (eocd < 0) return null;
  const count = dv.getUint16(eocd + 10, true);
  let p = dv.getUint32(eocd + 16, true);
  const out = [];
  for (let n = 0; n < count && p + 46 <= bytes.length; n++) {
    if (dv.getUint32(p, true) !== 0x02014b50) break;
    const flags = dv.getUint16(p + 8, true), method = dv.getUint16(p + 10, true);
    const csize = dv.getUint32(p + 20, true), nlen = dv.getUint16(p + 28, true);
    const elen = dv.getUint16(p + 30, true), clen = dv.getUint16(p + 32, true), local = dv.getUint32(p + 42, true);
    const name = new TextDecoder().decode(bytes.slice(p + 46, p + 46 + nlen));
    out.push({ name, encrypted: !!(flags & 1), method, csize, local });
    p += 46 + nlen + elen + clen;
  }
  return out;
}

export async function readZipEntry(bytes, entry) {
  const dv = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const p = entry.local;
  if (p + 30 > bytes.length || dv.getUint32(p, true) !== 0x04034b50) return null;
  const start = p + 30 + dv.getUint16(p + 26, true) + dv.getUint16(p + 28, true);
  const data = bytes.slice(start, start + entry.csize);
  if (entry.method === 0) return data;
  if (entry.method !== 8 || typeof DecompressionStream === 'undefined') return null;
  try {
    const stream = new Blob([data]).stream().pipeThrough(new DecompressionStream('deflate-raw'));
    return new Uint8Array(await new Response(stream).arrayBuffer());
  } catch { return null; }
}

function latin(bytes) {
  return new TextDecoder('latin1').decode(bytes);
}

// A web page sent as an attachment is the classic fake login: it opens
// from the computer, where no browser warning has seen it.
function pageFindings(text, out) {
  const t = text.toLowerCase();
  if (/<input[^>]+type\s*=\s*["']?password/.test(t)) out.push({ level: 'high', id: 'att-password-form', detail: '' });
  else if (/<form\b/.test(t)) out.push({ level: 'medium', id: 'att-form', detail: '' });
  if (/<script\b|\bon(load|error|click)\s*=|javascript:/.test(t)) out.push({ level: 'medium', id: 'att-script', detail: '' });
  if (/http-equiv\s*=\s*["']?refresh|(window|document)\.location|location\.(href|replace)/.test(t)) out.push({ level: 'high', id: 'att-redirect', detail: '' });
  if (/\batob\s*\(|unescape\s*\(|fromcharcode/.test(t)) out.push({ level: 'medium', id: 'att-obfuscated', detail: '' });
}

function pdfFindings(text, out) {
  if (/\/(JavaScript|JS)\b/.test(text)) out.push({ level: 'high', id: 'att-pdf-js', detail: '' });
  if (/\/Launch\b/.test(text)) out.push({ level: 'high', id: 'att-pdf-launch', detail: '' });
  if (/\/EmbeddedFile\b/.test(text)) out.push({ level: 'medium', id: 'att-pdf-embedded', detail: '' });
  if (/\/OpenAction\b|\/AA\b/.test(text) && /\/(URI|JavaScript|JS|Launch)\b/.test(text)) out.push({ level: 'medium', id: 'att-pdf-autoaction', detail: '' });
  const uris = [...new Set([...text.matchAll(/\/URI\s*\(([^)]{4,300})\)/g)].map(m => m[1]))];
  for (const u of uris.slice(0, 50)) out.push(...checkLink(u, '').map(f => ({ ...f, id: 'att-' + f.id })));
  if (uris.length) out.push({ level: 'low', id: 'att-pdf-links', detail: uris.slice(0, 5).join('  ') });
}

// Everything that can be told about one attachment without opening it.
export async function inspectAttachment(att) {
  const name = att.name || '(unnamed)';
  const bytes = att.bytes || new Uint8Array();
  const out = [];
  const lower = name.toLowerCase();
  const ext = (lower.match(/\.([a-z0-9]+)$/) || [, ''])[1];
  const kind = sniff(bytes);

  if (/\.[a-z0-9]{2,5}\s*\.[a-z0-9]{2,5}$/i.test(name) && (EXEC_EXT.test(name) || SCRIPT_PAGE_EXT.test(name))) {
    out.push({ level: 'high', id: 'att-double-ext', detail: name });
  } else if (/[‮‭]/.test(name)) {
    out.push({ level: 'high', id: 'att-rtlo', detail: name });
  }
  if (EXEC_EXT.test(lower) || /^program/.test(kind) || kind === 'disk image (ISO)') {
    out.push({ level: 'high', id: 'att-program', detail: kind || ext });
  } else if (SCRIPT_PAGE_EXT.test(lower) || kind === 'web page (html)' || kind === 'svg') {
    out.push({ level: 'medium', id: 'att-page', detail: kind || ext });
  }
  if (EXPECT[ext] && kind && EXPECT[ext] !== kind) {
    out.push({ level: 'high', id: 'att-mismatch', detail: `.${ext} → ${kind}` });
  }
  if (MACRO_EXT.test(lower)) out.push({ level: 'high', id: 'att-macros', detail: '' });

  if (kind === 'web page (html)' || kind === 'svg' || SCRIPT_PAGE_EXT.test(lower)) {
    pageFindings(new TextDecoder().decode(bytes), out);
  }
  if (kind === 'pdf') pdfFindings(latin(bytes), out);
  if (kind === 'office (old format)' && /_VBA_PROJECT|VBA[\s\S]{0,40}Attribut|\bAutoOpen\b|Auto_Open|Document_Open|Workbook_Open/.test(latin(bytes))) {
    out.push({ level: 'high', id: 'att-macros', detail: '' });
  }
  if (kind === 'rar' || kind === '7z') out.push({ level: 'low', id: 'att-archive-unread', detail: kind });

  if (kind === 'zip') {
    const entries = zipEntries(bytes) || [];
    const office = entries.some(e => e.name === '[Content_Types].xml');
    if (entries.some(e => e.encrypted)) out.push({ level: 'high', id: 'att-encrypted', detail: '' });
    if (office) {
      if (entries.some(e => /vbaProject\.bin$/i.test(e.name))) out.push({ level: 'high', id: 'att-macros', detail: '' });
      if (entries.some(e => /(^|\/)(activeX|embeddings)\//i.test(e.name))) out.push({ level: 'medium', id: 'att-embedded', detail: '' });
      for (const e of entries.filter(x => /\.rels$/i.test(x.name)).slice(0, 40)) {
        const data = await readZipEntry(bytes, e);
        if (!data) continue;
        const xml = new TextDecoder().decode(data);
        for (const m of xml.matchAll(/<Relationship\b[^>]*>/g)) {
          const rel = m[0];
          if (!/TargetMode\s*=\s*"External"/i.test(rel)) continue;
          const target = (/Target\s*=\s*"([^"]+)"/.exec(rel) || [, ''])[1];
          if (/attachedTemplate|oleObject|frame|subDocument/i.test(rel)) out.push({ level: 'high', id: 'att-remote-template', detail: target });
          else if (/^https?:/i.test(target)) out.push(...checkLink(target, '').map(f => ({ ...f, id: 'att-' + f.id })));
        }
      }
    } else {
      const risky = entries.filter(e => EXEC_EXT.test(e.name) || SCRIPT_PAGE_EXT.test(e.name) || MACRO_EXT.test(e.name) || ARCHIVE_EXT.test(e.name));
      const doubles = entries.filter(e => /\.[a-z0-9]{2,5}\s*\.(exe|scr|js|vbs|lnk|bat|cmd|hta|html?)$/i.test(e.name));
      if (risky.length) out.push({ level: 'high', id: 'att-zip-risky', detail: [...new Set([...doubles, ...risky].map(e => e.name))].slice(0, 6).join(', ') });
      if (!entries.length) out.push({ level: 'low', id: 'att-archive-unread', detail: 'zip' });
    }
  }
  if (!out.length && !DOC_EXT.test(lower) && !kind) out.push({ level: 'low', id: 'att-unknown', detail: ext || '?' });
  let label = kind || ext;
  if (kind === 'zip' && /^(docx|docm|dotx|dotm|xlsx|xlsm|xltx|pptx|pptm|odt|ods|odp)$/.test(ext)) label = 'office document';
  return { name, size: bytes.length, kind: label, findings: out };
}
