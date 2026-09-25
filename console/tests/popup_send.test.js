// Esegue i veri handler inline con DOM/provider finti: nessun invio o Electron.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

async function sendPopup(file, response) {
  const html = fs.readFileSync(path.join(__dirname, '..', file), 'utf8');
  function handler(name) {
    // I due handler sono dichiarazioni top-level, terminate da una graffa
    // non indentata. Si esegue il sorgente della UI, non una sua copia.
    const found = html.match(new RegExp(`(?:async )?function ${name}\\(\\) \\{[\\s\\S]*?^\\}`, 'm'));
    assert.ok(found, `${name} presente in ${file}`);
    return found[0];
  }
  const elements = {};
  const values = {
    mailTo: 'cliente@example.com', replyTo: 'cliente@example.com',
    mailSubject: 'Preventivo', replySubject: 'Preventivo',
    mailBody: 'La bozza da conservare', replyText: 'La bozza da conservare',
    mailCc: 'ufficio@example.com', replyCc: 'ufficio@example.com', mailBcc: '',
    instruction: '',
  };
  for (const id of [...Object.keys(values), 'btnSend', 'sendLabel', 'sendCircle', 'status']) {
    elements[id] = { value: values[id] || '', disabled: false, textContent: '',
      style: { setProperty() {} } };
  }
  const state = { closed: 0, followups: [], alerts: [], requests: [] };
  const api = {
    close() { state.closed += 1; },
    async followupSave(data) { state.followups.push(data); },
  };
  const attachment = { name: 'scheda.pdf', data_b64: 'cGRm', type: 'application/pdf', dataUrl: 'preview' };
  const context = {
    document: { getElementById: id => elements[id] },
    window: { newMailWindowAPI: api, replyWindowAPI: api },
    API: 'http://fixture.invalid', accountId: 7, mailData: { account_id: 7, id: '42' },
    attachments: [attachment], followupHours: 24,
    sendTimer: null, sendRafId: null,
    setTimeout(fn) { fn(); }, clearTimeout() {}, cancelAnimationFrame() {},
    alert(message) { state.alerts.push(message); },
    async fetch(url, options) {
      state.requests.push({ url, body: JSON.parse(options.body) });
      if (response instanceof Error) throw response;
      return response;
    },
  };
  await vm.runInNewContext(`${handler('resetSendBtn')}\n${handler('execSend')}\nexecSend()`, context);
  return { state, elements, attachment };
}

for (const file of ['new_mail_window.html', 'reply_window.html']) {
  for (const status of [403, 503]) {
    test(`${file}: HTTP ${status} conserva bozza e allegati senza follow-up o chiusura`, async () => {
      const { state, elements, attachment } = await sendPopup(file, {
        ok: false, status, json: async () => ({ detail: 'Verifica utente annullata' }),
      });
      assert.equal(state.closed, 0);
      assert.equal(state.followups.length, 0);
      assert.equal(elements.btnSend.disabled, false);
      assert.equal(elements.mailBody.value, 'La bozza da conservare');
      assert.equal(elements.replyText.value, 'La bozza da conservare');
      assert.equal(attachment.data_b64, 'cGRm');
      assert.match(elements.status.textContent + state.alerts.join(' '), /Verifica utente annullata/);
    });
  }

  test(`${file}: rifiuto del provider su HTTP 200 non e' successo`, async () => {
    const { state, elements } = await sendPopup(file, {
      ok: true, status: 200, json: async () => ({ success: false, error: 'SMTP rifiutato' }),
    });
    assert.equal(state.closed, 0);
    assert.equal(state.followups.length, 0);
    assert.equal(elements.btnSend.disabled, false);
    assert.match(elements.status.textContent + state.alerts.join(' '), /SMTP rifiutato/);
  });

  test(`${file}: risposta non JSON non conferma l'invio`, async () => {
    const { state, elements } = await sendPopup(file, {
      ok: true, status: 200, json: async () => { throw new Error('JSON non valido'); },
    });
    assert.equal(state.closed, 0);
    assert.equal(state.followups.length, 0);
    assert.equal(elements.btnSend.disabled, false);
  });

  test(`${file}: errore di rete mantiene la bozza`, async () => {
    const { state, elements } = await sendPopup(file, new Error('Connessione assente'));
    assert.equal(state.closed, 0);
    assert.equal(state.followups.length, 0);
    assert.equal(elements.btnSend.disabled, false);
    assert.match(elements.status.textContent + state.alerts.join(' '), /Connessione assente/);
  });

  test(`${file}: dry-run non chiude e non crea follow-up`, async () => {
    const { state, elements } = await sendPopup(file, {
      ok: true, status: 200, json: async () => ({ success: true, dryrun: true }),
    });
    assert.equal(state.closed, 0);
    assert.equal(state.followups.length, 0);
    assert.match(elements.status.textContent + state.alerts.join(' '), /nessuna mail inviata/);
  });

  test(`${file}: solo invio confermato chiude e salva follow-up`, async () => {
    const { state } = await sendPopup(file, {
      ok: true, status: 200, json: async () => ({ success: true }),
    });
    assert.equal(state.closed, 1);
    assert.equal(state.followups.length, 1);
    assert.equal(state.requests.length, 1);
    assert.equal(state.requests[0].body.body, 'La bozza da conservare');
    assert.equal(state.requests[0].body.attachments[0].data_b64, 'cGRm');
    assert.equal(state.requests[0].body.attachments[0].dataUrl, undefined);
  });
}
