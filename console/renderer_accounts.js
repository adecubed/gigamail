// renderer_accounts.js — selettore account, aggiunta IMAP dalla modale,
// eliminazione con menu contestuale. Estratto da renderer.js (stesso scope
// globale: activeAccountId, mailFolderCache restano dichiarati la').
// Le parti pure stanno in window.AccountsView (tests/accounts_view.test.js).

const AccountsView = (() => {
  /** <option> del selettore: nome e tipo escapati, quello attivo selezionato. */
  function optionsHtml(accounts) {
    if (!Array.isArray(accounts) || !accounts.length) {
      return '<option value="">' + T('no_account', 'Nessun account') + '</option>';
    }
    return accounts.map(a =>
      `<option value="${esc(a.id)}"${a.active ? ' selected' : ''}>${esc(a.name)} (${esc(a.type)})</option>`).join('');
  }

  /** L'account da mostrare come attivo: quello marcato, altrimenti il primo. */
  function activeOf(accounts) {
    return Array.isArray(accounts) ? (accounts.find(a => a.active) || accounts[0] || null) : null;
  }

  return { optionsHtml, activeOf };
})();
if (typeof window !== 'undefined') window.AccountsView = AccountsView;


async function loadAccounts() {
  const started = performance.now();
  try {
    const accounts = await api.getAccounts();
    const select = byId('accountSelect');
    if (!select) return;
    select.innerHTML = AccountsView.optionsHtml(accounts);
    const active = AccountsView.activeOf(accounts);
    activeAccountId = active?.id ?? null;
    mailFolderCache = [];
    renderCustomFolders();
    if (activeAccountId) {
      loadMailFolders(false).catch(e => console.error('loadMailFolders:', e));
    }
    console.log(`[ADE MAIL UI TIMING] loadAccounts=${Math.round(performance.now() - started)}ms count=${Array.isArray(accounts) ? accounts.length : 0}`);
  } catch (e) { console.error('loadAccounts:', e); }
}

async function saveImapAccount() {
  const name     = byId('imapName')?.value.trim() || '';
  const email    = byId('imapEmail')?.value.trim() || '';
  const password = byId('imapPassword')?.value.trim() || '';
  const provider = byId('imapProvider')?.value || 'aruba';
  const imapHost = byId('imapHost')?.value.trim() || null;
  const smtpHost = byId('smtpHost')?.value.trim() || null;
  const status   = byId('imapStatus');
  if (!name || !email || !password) { if (status) status.textContent = '✕ Compila nome, email e password'; return; }
  if (status) status.textContent = '⚡ Connessione in corso...';
  try {
    const result = await api.addImapAccount(name, email, password, provider, imapHost, null, smtpHost, null);
    if (result.success) {
      if (status) status.textContent = '✓ Account aggiunto';
      activeAccountId = result.account_id;
      setTimeout(async () => {
        setHidden('imapOverlay', true);
        await loadAccounts();
        await refreshCurrentFolder();
      }, 800);
    } else if (status) {
      status.textContent = `✕ Errore: ${result.detail || 'connessione fallita'}`;
    }
  } catch (e) { if (status) status.textContent = `✕ ${String(e).slice(0, 80)}`; }
}

// ── ELIMINA ACCOUNT (tasto destro su select account) ──────────────────────────
async function deleteCurrentAccount(accountId) {
  if (!accountId) return;
  const sel = byId('accountSelect');
  const label = sel?.selectedOptions?.[0]?.textContent || `account ${accountId}`;
  const ok = confirm(
    `Eliminare "${label}"?\n\n` +
    `Verranno rimossi l'account e tutte le sue mail indicizzate localmente.\n` +
    `Le mail sui server (Microsoft/IMAP) NON vengono toccate.`
  );
  if (!ok) return;

  try {
    const r = await fetch(`${window.GIGAMAIL_API}/accounts/${accountId}`, { method: 'DELETE' });
    if (!r.ok) {
      const err = await r.text();
      alert(`Errore eliminazione: ${err.slice(0, 200)}`);
      return;
    }
    const data = await r.json();
    const n = (data.data_deleted && data.data_deleted.threads) || 0;
    console.log('[DELETE ACCOUNT]', data);
    if (n > 0) console.log(`Account eliminato. ${n} mail indicizzate rimosse.`);
    activeAccountId = null;
    await loadAccounts();
    await refreshCurrentFolder().catch(() => {});
  } catch (e) {
    console.error('deleteCurrentAccount:', e);
    alert(`Errore: ${String(e).slice(0, 200)}`);
  }
}

// Menu contestuale (tasto destro) sulla select degli account
(() => {
  const sel = byId('accountSelect');
  if (!sel || sel.dataset.ctxBound) return;
  sel.dataset.ctxBound = '1';
  sel.addEventListener('contextmenu', (e) => {
    e.preventDefault();
    document.getElementById('accountCtxMenu')?.remove();

    const menu = document.createElement('div');
    menu.id = 'accountCtxMenu';
    menu.style.cssText =
      'position:fixed;z-index:99999;background:#fff;border:1px solid #ccc;' +
      'border-radius:6px;box-shadow:0 4px 14px rgba(0,0,0,.18);padding:4px 0;' +
      'font-size:13px;min-width:170px';
    menu.style.left = e.clientX + 'px';
    menu.style.top = e.clientY + 'px';

    const item = document.createElement('div');
    item.textContent = (typeof T === 'function' ? T('delete_account', 'Elimina account') : 'Elimina account');
    item.style.cssText = 'padding:7px 14px;cursor:pointer;color:#c0392b';
    item.onmouseenter = () => { item.style.background = '#f5f5f5'; };
    item.onmouseleave = () => { item.style.background = ''; };
    item.onclick = () => {
      menu.remove();
      deleteCurrentAccount(sel.value || activeAccountId);
    };
    menu.appendChild(item);
    document.body.appendChild(menu);

    const close = () => { menu.remove(); document.removeEventListener('click', close); };
    setTimeout(() => document.addEventListener('click', close), 0);
  });
})();

// ── Binding del selettore account e della modale IMAP ────────────────────────
function bindAccountEvents() {
  on('accountSelect', 'change', async (e) => {
    const id = parseInt(e.target.value, 10);
    if (!id) return;
    try {
      await api.switchAccount(id);
      activeAccountId = id;
      customFolderCountsRequestId += 1;
      customFolderNewCounts = new Map();
      mailFolderCache = [];
      currentFolder = 'inbox';
      currentFolderLabel = 'inbox';
      renderCustomFolders();
      selectedMailId = null;
      currentMailIndex = -1;
      currentMailList = [];
      updateVoiceContext?.(null, -1);
      document.querySelectorAll('.mail-item').forEach(el => el.classList.remove('selected'));
      resetMailDetail();
      await loadMailFolders(false);
      await refreshCurrentFolder();
      await loadEvents();
    }
    catch (e) { console.error('switchAccount:', e); }
  });

  on('btnAddAccount',   'click', () => setHidden('imapOverlay', false));
  on('btnCloseImap',    'click', () => setHidden('imapOverlay', true));

  // Bottone 👤 ID per configurare identity account
  const _acSel = byId('accountSelect');
  const _btnIdExisting = byId('btnIdentityAccount');
  if (_btnIdExisting && _acSel) {
    _btnIdExisting.addEventListener('click', () => {
      const selId = parseInt(_acSel.value, 10);
      const selName = _acSel.options[_acSel.selectedIndex]?.text || '';
      if (selId) openIdentityModal(selId, selName);
    });
  }

  on('imapProvider',    'change', (e) => {
    const custom = byId('imapCustomFields');
    if (custom) custom.style.display = e.target.value === 'custom' ? 'block' : 'none';
  });
  on('btnAddMicrosoft', 'click', () => { setHidden('imapOverlay', true); setHidden('loginOverlay', false); });

  on('btnAddGmail', 'click', () => {
    // Precompila campi IMAP per Gmail
    const prov = document.getElementById('imapProvider');
    if (prov) { prov.value = 'gmail'; prov.dispatchEvent(new Event('change')); }
    // Mostra hint password app
    const status = document.getElementById('imapStatus');
    if (status) status.innerHTML = '<span style="color:rgba(180,40,30,0.8)">Gmail richiede una <a href="https://myaccount.google.com/apppasswords" target="_blank" style="color:var(--accent)">password per le app</a> (non la password Google normale)</span>';
    const nameEl = document.getElementById('imapName');
    if (nameEl && !nameEl.value) nameEl.placeholder = 'Es: Gmail Lavoro';
    const emailEl = document.getElementById('imapEmail');
    if (emailEl) emailEl.focus();
  });
  on('btnSaveImap',     'click', saveImapAccount);
}
