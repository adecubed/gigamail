(function() {
  'use strict';

  const mailList = document.getElementById('mailList');
  if (!mailList) return;

  function openNative(id, folder, accountId) {
    if (window.electronAPI?.openMailWindow) {
      window.electronAPI.openMailWindow({ id, folder: folder || null, account_id: accountId || null });
    }
  }

  function openDetail(id, folder, accountId) {
    if (typeof window.loadMailDetail === 'function') {
      window.loadMailDetail(id, folder, accountId);
    }
  }

  function resetDetail() {
    if (typeof window.resetMailDetail === 'function') {
      window.resetMailDetail();
    } else {
      const detail = document.getElementById('mailDetail');
      if (detail) { detail.innerHTML = ''; detail.className = 'main-area'; }
    }
  }

  let pendingOpen = null;

  // Click singolo → pannello destro
mailList.addEventListener('click', (e) => {
    const item = e.target.closest('.mail-item');
    if (!item || !item.dataset.id) return;

    mailList.querySelectorAll('.mail-item').forEach(el => el.classList.remove('selected'));
    item.classList.add('selected');

    const id        = item.dataset.id;
    const folder    = item.dataset.folder || null;
    const accountId = item.dataset.accountId || window.activeAccountId || window._activeAccountId || null;

    window._currentMailId     = id;
    window._currentMailFolder = folder;
    window._activeAccountId   = accountId;

    clearTimeout(pendingOpen);
    pendingOpen = setTimeout(async () => {
      pendingOpen = null;
      if (window.outerWidth < 500) {
        await window.electronAPI?.toggleCompact();
      }
      openDetail(id, folder, accountId);
    }, 300);

  }, true);

  // Doppio click → popup nativo + dashboard nel pannello
  mailList.addEventListener('dblclick', (e) => {
    const item = e.target.closest('.mail-item');
    if (!item || !item.dataset.id) return;

    clearTimeout(pendingOpen);
    pendingOpen = null;

    const id        = item.dataset.id;
    const folder    = item.dataset.folder || null;
    const accountId = item.dataset.accountId || window.activeAccountId || window._activeAccountId || null;

    window._currentMailId     = id;
    window._currentMailFolder = folder;
    window._activeAccountId   = accountId;

    if (typeof window.cancelMailDetail === 'function') window.cancelMailDetail();
    openNative(id, folder, accountId);
    resetDetail(); // mostra dashboard

    e.stopImmediatePropagation();
    e.preventDefault();
  }, true);

  // ⤢ → popup nativo + dashboard nel pannello
  document.addEventListener('click', (e) => {
    const btn = e.target.id === 'btnPopOut' ? e.target : e.target.closest?.('#btnPopOut');
    if (!btn) return;
    e.stopImmediatePropagation();
    openNative(window._currentMailId, window._currentMailFolder, window._activeAccountId);
    setTimeout(() => resetDetail(), 50); // piccolo delay per non conflittare con l'animazione
  }, true);

})();
