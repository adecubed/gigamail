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
  if (name || /attachment/i.test(disp)) { acc.attachments.push(name || '(unnamed)'); return; }
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

// One finding per suspicious link. `text` is what the reader sees.
export function checkLink(href, text) {
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

const RISKY_EXT = /\.(html?|exe|scr|js|vbs|iso|img|zip|rar|7z|docm|xlsm|pptm|lnk|one|svg|bat|cmd|msi|jar)$/i;

// ---- Headers ---------------------------------------------------------------

export function headerSignals(headers) {
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
export function analyse(parsed, hidden, visibleText, links) {
  const findings = [...headerSignals(parsed.headers)];
  for (const l of links) findings.push(...checkLink(l.href, l.text));
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
  const risky = parsed.attachments.filter(n => RISKY_EXT.test(n));
  if (risky.length) findings.push({ level: 'high', id: 'attachment', detail: risky.join(', ') });
  return { findings, verdict: verdict(findings) };
}

// Links in plain text: what is shown is the link itself.
export function plainLinks(text) {
  return (String(text || '').match(/https?:\/\/[^\s<>"')]+/g) || []).map(u => ({ href: u, text: u }));
}
