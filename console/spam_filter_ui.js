// spam_filter_ui.js — "Blocca mail simili": il filtro spam per oggetto,
// mittente o testo, da qualunque indirizzo. Lo stesso pannello si apre dalla
// mail aperta (precompilato con il suo oggetto) e da Automazioni; l'elenco
// dei filtri sta in Automazioni. Backend: /spam_filters (http_api/spam.py).
(function () {
  const tr = (key, fallback) => (typeof T === 'function' ? T(key, fallback) : fallback);
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
  const api = () => window.ademail || window.electronAPI || {};
  let afterSave = null;

  function open(prefill = {}, onSaved = null) {
    afterSave = onSaved;
    if ($('sfField')) $('sfField').value = prefill.field || 'subject';
    if ($('sfContains')) $('sfContains').value = prefill.contains || '';
    if ($('sfAction')) $('sfAction').value = 'spam';
    if ($('sfAllAccounts')) $('sfAllAccounts').checked = false;
    if ($('spamFilterStatus')) $('spamFilterStatus').textContent = '';
    $('spamFilterPanel')?.classList.remove('hidden');
    setTimeout(() => { const i = $('sfContains'); if (i) { i.focus(); i.select(); } }, 50);
  }

  function close() { $('spamFilterPanel')?.classList.add('hidden'); }

  async function confirm() {
    const btn = $('btnConfirmSpamFilter');
    const status = $('spamFilterStatus');
    const body = {
      field: $('sfField')?.value || 'subject',
      contains: ($('sfContains')?.value || '').trim(),
      action: $('sfAction')?.value || 'spam',
      all_accounts: !!$('sfAllAccounts')?.checked,
      account_id: (typeof activeAccountId !== 'undefined' && activeAccountId) ? activeAccountId : null,
      apply_now: true,
    };
    if (body.contains.length < 3) { if (status) status.textContent = tr('sf_too_short', 'Almeno 3 caratteri.'); return; }
    if (btn) btn.disabled = true;
    try {
      const r = await api().createSpamFilter(body);
      close();
      const moved = Number(r?.moved || 0);
      if (typeof showToast === 'function') {
        showToast(tr('sf_saved', 'Filtro salvato') + (moved ? ' · ' + tr('sf_moved', '{n} mail spostate').replace('{n}', moved) : ''), 'success');
      }
      await refreshList();
      if (afterSave) await afterSave(r);
    } catch (e) {
      if (status) status.textContent = e.message || String(e);
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  function fieldLabel(f) {
    return f === 'from' ? tr('sf_field_from', 'Mittente')
      : f === 'body' ? tr('sf_field_body', 'Oggetto o testo') : tr('sf_field_subject', 'Oggetto');
  }

  function card(f, accounts) {
    const acc = f.account_id == null ? tr('sf_every_account', 'tutti gli account')
      : (accounts.find((a) => Number(a.id) === Number(f.account_id))?.name || `#${f.account_id}`);
    const action = f.action === 'trash' ? tr('sf_action_trash', 'Sposta nel cestino') : tr('sf_action_spam', 'Sposta nello spam');
    return `<div class="ai-card-row sf-row" style="justify-content:space-between;gap:8px">
      <div style="min-width:0">
        <div class="ai-card-title" style="font-size:12px">${esc(fieldLabel(f.field))}: “${esc(f.contains)}”</div>
        <div class="ai-card-sub">${esc(action)} · ${esc(acc)} · ${esc(tr('sf_hits', '{n} bloccate').replace('{n}', f.hits || 0))}</div>
      </div>
      <button class="chip-btn danger" data-sf-delete="${esc(f.id)}" title="${esc(tr('delete', 'Elimina'))}">✕</button>
    </div>`;
  }

  async function refreshList() {
    const box = $('spamFiltersList');
    if (!box) return;
    try {
      const [filters, accounts] = await Promise.all([
        api().listSpamFilters(), api().getAccounts ? api().getAccounts().catch(() => []) : [],
      ]);
      box.innerHTML = filters.length ? filters.map((f) => card(f, accounts || [])).join('')
        : `<div class="hint">${esc(tr('sf_none', 'Nessun filtro.'))}</div>`;
    } catch (e) {
      box.innerHTML = `<div class="hint">${esc(e.message || e)}</div>`;
    }
  }

  function bind() {
    $('btnCloseSpamFilter')?.addEventListener('click', close);
    $('btnConfirmSpamFilter')?.addEventListener('click', confirm);
    $('sfContains')?.addEventListener('keydown', (e) => { if (e.key === 'Enter') confirm(); });
    $('btnNewSpamFilter')?.addEventListener('click', () => open({}));
    $('spamFiltersList')?.addEventListener('click', async (e) => {
      const b = e.target.closest('[data-sf-delete]');
      if (!b) return;
      try { await api().deleteSpamFilter(b.dataset.sfDelete); await refreshList(); }
      catch (err) { if (typeof showToast === 'function') showToast(err.message || String(err), 'error'); }
    });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', bind);
  else bind();

  const SpamFilterUI = { open, close, refreshList, card, fieldLabel };
  if (typeof window !== 'undefined') window.SpamFilterUI = SpamFilterUI;
  if (typeof module !== 'undefined' && module.exports) module.exports = SpamFilterUI;
})();
