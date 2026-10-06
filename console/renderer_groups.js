// renderer_groups.js — account groups: several accounts shown as one.
//
// A group is a view. Dragging one account tile onto another makes a group;
// its tile sums the counters and its mail list mixes the members' mail by
// date. Every mail keeps the account it belongs to, and acting on it
// (open, reply, delete, move) uses that account. "Split" removes the group.
// The pure parts live in window.AccountGroups (tests/account_groups.test.js).

const AccountGroups = (() => {
  /** Dashboard tiles: a group takes the place of its first account. */
  function tiles(accounts, groups) {
    const list = Array.isArray(accounts) ? accounts : [];
    const known = new Map(list.map(a => [Number(a.id), a]));
    const groupOf = new Map();
    (Array.isArray(groups) ? groups : []).forEach(g => {
      const ids = (g.account_ids || []).map(Number).filter(id => known.has(id));
      if (ids.length < 2) return;
      const group = { id: g.id, account_ids: ids };
      ids.forEach(id => groupOf.set(id, group));
    });
    const out = [];
    const placed = new Set();
    list.forEach(a => {
      const group = groupOf.get(Number(a.id));
      if (!group) { out.push({ group: null, accounts: [a] }); return; }
      if (placed.has(group.id)) return;
      placed.add(group.id);
      out.push({ group, accounts: group.account_ids.map(id => known.get(id)) });
    });
    return out;
  }

  /** When a mail arrived (or was sent), as a timestamp; 0 if unreadable. */
  function when(m) {
    const raw = String(m?.receivedDateTime || m?.sentDateTime || m?.createdDateTime || '');
    return Date.parse(raw.replace(/\s*\([^)]*\)\s*$/, '')) || 0;
  }

  /** One list from several accounts, newest first; each mail remembers its
   *  account. `lists` is [{account, mails}]. With `pageSize`, the list
   *  stops where the busiest account's page ends: past that point that
   *  account has older mail we did not fetch, and showing the others'
   *  would leave holes. */
  function mergeLists(lists, pageSize) {
    const all = [];
    let cutoff = 0;
    (lists || []).forEach(({ account, mails }) => {
      const page = Array.isArray(mails) ? mails : [];
      page.forEach(m => all.push({
        ...m,
        _accountId: Number(account.id),
        _accountLabel: account.name || account.email || '',   // short: it shares a line with the sender
      }));
      if (pageSize && page.length >= pageSize) {
        const oldest = Math.min(...page.map(when).filter(Boolean));
        if (Number.isFinite(oldest)) cutoff = Math.max(cutoff, oldest);
      }
    });
    return all
      .filter(m => !cutoff || !when(m) || when(m) >= cutoff)
      .sort((a, b) => when(b) - when(a));
  }

  function label(accounts) {
    return (accounts || []).map(a => a.name || a.email || '').filter(Boolean).join(' + ');
  }

  /** Counters of a tile: the members' numbers added up, and the most
   *  recent "last mail" among them. `stats` is one entry per account. */
  function sum(stats) {
    const out = { unread: 0, sentToday: 0, lastMail: '', lastTs: -1 };
    (stats || []).forEach(s => {
      out.unread += Number(s?.unread) || 0;
      out.sentToday += Number(s?.sentToday) || 0;
      if (s?.lastMail && (Number(s.lastTs) || 0) > out.lastTs) {
        out.lastMail = s.lastMail;
        out.lastTs = Number(s.lastTs) || 0;
      }
    });
    return out;
  }

  /** HTML of one dashboard tile. Everything from the account is escaped. */
  function tileHtml(tile, stats, dotColor, canGroup) {
    const accounts = tile.accounts || [];
    const group = tile.group;
    const first = accounts[0] || {};
    const title = group ? label(accounts) : (first.name || first.email || 'Account');
    const emails = accounts.map(a => a.email || '').filter(Boolean).join(', ');
    const s = stats || { unread: 0, sentToday: 0, lastMail: '' };
    const split = group
      ? `<span data-split-group="${esc(group.id)}" title="${esc(T('split_accounts_hint', 'Torna a vederli separati'))}" style="cursor:pointer;text-decoration:underline;">${esc(T('split_accounts', 'Separa'))}</span>`
      : '';
    return `<div data-tile="1" data-account-id="${esc(first.id)}"${group ? ` data-group-id="${esc(group.id)}"` : ''}${canGroup ? ` draggable="true" title="${esc(T('merge_hint', 'Trascina su un altro account per unirli'))}"` : ''} style="background:white;border:1px solid rgba(0,0,0,0.14);border-radius:14px;box-shadow:0 2px 8px rgba(0,0,0,0.07);padding:12px 14px;cursor:pointer;transition:box-shadow 0.15s;min-width:0;overflow:hidden;"
        onmouseover="this.style.boxShadow='0 6px 20px rgba(0,0,0,0.22)'"
        onmouseout="this.style.boxShadow='0 2px 8px rgba(0,0,0,0.07)'">
        <div style="display:flex;align-items:center;gap:7px;margin-bottom:5px;">
          <div style="width:9px;height:9px;border-radius:50%;background:${dotColor};border:1.5px solid rgba(0,0,0,0.2);flex-shrink:0;"></div>
          <div style="font-size:12px;font-weight:500;color:rgba(0,0,0,0.82);flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${esc(title)}</div>
        </div>
        <div style="font-size:10px;color:rgba(0,0,0,0.55);margin-bottom:8px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${esc(emails)}</div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:5px;margin-bottom:7px;">
          <div style="background:rgba(0,0,0,0.04);border-radius:8px;padding:7px 9px;">
            <div style="font-size:20px;font-weight:500;line-height:1;color:${s.unread > 0 ? '#993556' : 'rgba(0,0,0,0.82)'};">${Number(s.unread) || 0}</div>
            <div style="font-size:9px;color:rgba(0,0,0,0.55);margin-top:2px;">${T('unread', 'Non lette')}</div>
          </div>
          <div style="background:rgba(0,0,0,0.04);border-radius:8px;padding:7px 9px;">
            <div style="font-size:20px;font-weight:500;line-height:1;color:rgba(0,0,0,0.82);">${Number(s.sentToday) || 0}</div>
            <div style="font-size:9px;color:rgba(0,0,0,0.55);margin-top:2px;">${T('sent_today', 'Inviate oggi')}</div>
          </div>
        </div>
        ${s.lastMail ? `<div style="font-size:10px;color:rgba(0,0,0,0.55);background:rgba(0,0,0,0.04);border-radius:7px;padding:5px 8px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">↙ ${esc(s.lastMail)}</div>` : ''}
        <div style="display:flex;justify-content:space-between;gap:8px;font-size:10px;color:rgba(0,0,0,0.55);margin-top:6px;">
          <span>${split}</span>
          <span>${T('goto_account', "Vai all'account →")}</span>
        </div>
      </div>`;
  }

  return { tiles, when, mergeLists, label, sum, tileHtml };
})();
if (typeof window !== 'undefined') window.AccountGroups = AccountGroups;


/** The group being viewed, with its account objects; null in the normal,
 *  one-account view. */
function groupFromTile(tile) {
  return tile.group
    ? { id: tile.group.id, account_ids: tile.group.account_ids.slice(), accounts: tile.accounts.slice() }
    : null;
}

/** In a merged view every mail belongs to one of the group's accounts:
 *  before acting on a mail, its account becomes the active one. */
function useAccountOfItem(accountId) {
  const id = parseInt(accountId, 10);
  if (!activeGroup || !id || id === Number(activeAccountId)) return;
  activeAccountId = id;
  window.activeAccountId = id;
  window._activeAccountId = id;
  const sel = byId('accountSelect');
  if (sel) sel.value = String(id);
  // Folders (the move panel, the folder chips) follow the account.
  customFolderCountsRequestId += 1;
  customFolderNewCounts = new Map();
  mailFolderCache = [];
  api.switchAccount(id).catch(e => console.error('switchAccount:', e));
  loadMailFolders(false).catch(e => console.error('loadMailFolders:', e));
}

/** Leave the merged view (an account was picked, or the group is gone). */
function leaveGroup() {
  if (!activeGroup) return;
  activeGroup = null;
  setFolderTitle(currentFolder, currentFolderLabel);   // drop the group's name
}

window._openGroup = async (group) => {
  try {
    activeGroup = group;
    const ids = group.account_ids.map(Number);
    if (!ids.includes(Number(activeAccountId))) activeAccountId = ids[0];
    window.activeAccountId = activeAccountId;
    window._activeAccountId = activeAccountId;
    window._currentMailId = null;
    window._currentMailFolder = null;
    const sel = byId('accountSelect');
    if (sel) sel.value = String(activeAccountId);
    customFolderCountsRequestId += 1;
    customFolderNewCounts = new Map();
    mailFolderCache = [];
    renderCustomFolders();
    api.switchAccount(activeAccountId).catch(e => console.error('switchAccount:', e));
    loadMailFolders(false).catch(e => console.error('loadMailFolders:', e));
    await openFolder('inbox', 'btnShowInbox');
    loadEvents().catch(e => console.error('loadEvents:', e));
  } catch (e) { console.error('_openGroup:', e); }
};

/** Click, drag-and-drop and "Split" on the dashboard tiles. Bound after
 *  every render, also when the dashboard is restored from its last HTML. */
function bindDashboardTiles(root, tileList) {
  if (!root) return;
  const redraw = () => { renderDashboard._last = null; renderDashboard(); };
  root.querySelectorAll('[data-tile]').forEach((el, idx) => {
    const tile = (tileList || [])[idx];
    el.addEventListener('click', (e) => {
      if (e.target.closest('[data-split-group]')) return;
      if (tile?.group) window._openGroup(groupFromTile(tile));
      else window._switchAccount && window._switchAccount(Number(el.dataset.accountId));
    });
    if (el.getAttribute('draggable') !== 'true') return;
    el.addEventListener('dragstart', (e) => {
      e.dataTransfer.setData('text/x-gigamail-account', String(el.dataset.accountId));
      e.dataTransfer.effectAllowed = 'move';
    });
    el.addEventListener('dragover', (e) => {
      if (![...e.dataTransfer.types].includes('text/x-gigamail-account')) return;
      e.preventDefault();
      el.style.outline = '2px dashed rgba(0,0,0,0.45)';
    });
    el.addEventListener('dragleave', () => { el.style.outline = ''; });
    el.addEventListener('drop', async (e) => {
      e.preventDefault();
      el.style.outline = '';
      const source = parseInt(e.dataTransfer.getData('text/x-gigamail-account'), 10);
      const target = parseInt(el.dataset.accountId, 10);
      if (!source || !target || source === target) return;
      try {
        await api.mergeAccounts(source, target);
        showToast(T('accounts_merged', 'Account uniti'), 'success');
        // The group on screen may have just changed: back to one account,
        // the new tile opens the new group.
        if (activeGroup) { leaveGroup(); refreshCurrentFolder().catch(() => {}); }
      } catch (err) {
        // Dropped on its own group, or the backend said no: nothing changed.
        console.error('mergeAccounts:', err);
      }
      redraw();
    });
  });
  root.querySelectorAll('[data-split-group]').forEach((el) => {
    el.addEventListener('click', async (e) => {
      e.stopPropagation();
      const id = parseInt(el.dataset.splitGroup, 10);
      try {
        await api.splitAccountGroup(id);
        showToast(T('accounts_split', 'Account separati'), 'success');
      } catch (err) { console.error('splitAccountGroup:', err); }
      if (activeGroup && Number(activeGroup.id) === id) {
        leaveGroup();
        refreshCurrentFolder().catch(() => {});
      }
      redraw();
    });
  });
}
