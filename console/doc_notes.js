/**
 * doc_notes.js: what the agent will not read well in a rule's documents.
 *
 * A rule answers from its documents. One too long to go in whole, a workbook
 * with old sheets next to the current one, a page that is only a picture:
 * each gave wrong or empty drafts, and nothing had said so when the document
 * was attached. The backend reads the document the way a draft does
 * (POST /documents/check) and this turns its notes into sentences, shown in
 * the rule form and on the rule cards.
 */
(function () {
  const lang = () => {
    try { return localStorage.getItem('ade_lang') || 'it'; } catch (_) { return 'it'; }
  };
  const T = (it, en, zh) => (lang() === 'it' ? it : lang() === 'zh' ? (zh || en) : en);
  const num = (n) => Number(n || 0).toLocaleString(lang() === 'it' ? 'it-IT' : 'en-US');

  function sentence(note) {
    switch (note.code) {
      case 'unreadable':
        return T('non si riesce a leggere: l\'agente non lo vedrà.',
          'cannot be read: the agent will not see it.',
          '无法读取：助手看不到它。');
      case 'no_text':
        return T('non contiene testo (una scansione o un disegno): l\'agente può allegarlo, non leggerlo.',
          'has no text in it (a scan or a drawing): the agent can attach it, not read it.',
          '不含文字（扫描件或图纸）：助手可以附上它，但无法阅读。');
      case 'too_long':
        return T(`è lungo ${num(note.chars)} caratteri e in una bozza ne entrano ${num(note.limit)}: all'agente arrivano l'inizio e i passaggi che corrispondono alla mail. Togli quello che non serve.`,
          `is ${num(note.chars)} characters long and a draft takes ${num(note.limit)}: the agent gets its beginning and the passages matching the mail. Remove what is not needed.`,
          `长 ${num(note.chars)} 个字符，而草稿只能容纳 ${num(note.limit)} 个：助手只会看到开头和与邮件相关的段落。请删除不需要的内容。`);
      case 'sheets': {
        const names = (note.names || []).join(', ');
        return T(`ha ${note.names.length} fogli (${names}): l'agente li legge tutti, anche quelli superati. Lascia solo quello valido.`,
          `has ${note.names.length} sheets (${names}): the agent reads them all, the outdated ones too. Keep only the current one.`,
          `有 ${note.names.length} 个工作表（${names}）：助手会全部读取，包括过时的。请只保留有效的那个。`);
      }
      case 'slow':
        return T(`ci vogliono ${num(note.seconds)} secondi per leggerlo, a ogni bozza.`,
          `takes ${num(note.seconds)} seconds to read, at every draft.`,
          `每次起草都需要 ${num(note.seconds)} 秒来读取。`);
      default:
        return '';
    }
  }

  // [{name, text}] for the documents that have something to say.
  function lines(reports) {
    const out = [];
    for (const r of reports || []) {
      for (const n of (r && r.notes) || []) {
        const text = sentence(n);
        if (text) out.push({ name: r.name || '', text });
      }
    }
    return out;
  }

  function fill(box, reports) {
    if (!box) return;
    box.textContent = '';
    const found = lines(reports);
    box.style.display = found.length ? '' : 'none';
    for (const l of found) {
      const row = box.ownerDocument.createElement('div');
      row.className = 'doc-note';
      const name = box.ownerDocument.createElement('strong');
      name.textContent = l.name;
      row.append('⚠ ', name, ' ' + l.text);
      box.appendChild(row);
    }
  }

  // Asks the backend and fills `box`; only the latest call for a box draws.
  const asked = new WeakMap();
  async function show(box, paths, api) {
    if (!box) return;
    const mine = (asked.get(box) || 0) + 1;
    asked.set(box, mine);
    if (!paths || !paths.length) { fill(box, []); return; }
    let reports;
    try {
      reports = await api('/documents/check', { method: 'POST', body: JSON.stringify({ paths }) });
    } catch (_) {
      return;   // unknown: say nothing rather than something false
    }
    if (asked.get(box) === mine) fill(box, reports);
  }

  window.DocNotes = { lines, fill, show };
})();
