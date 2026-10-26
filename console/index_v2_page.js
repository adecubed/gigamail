// index_v2_page.js — the script of index_v2.html, moved out of the page so that the
// Content-Security-Policy can forbid inline scripts (no 'unsafe-inline').
function makeDraggable(el,handle){
  let drag=false,sx,sy,ox,oy;
  handle.addEventListener('mousedown',e=>{
    if(e.target.classList.contains('popup-tb-dot'))return;
    drag=true; el.style.transform='none';
    const r=el.getBoundingClientRect();
    sx=e.clientX;sy=e.clientY;ox=r.left;oy=r.top;
    el.classList.add('dragging');e.preventDefault();
  });
  document.addEventListener('mousemove',e=>{
    if(!drag)return;
    el.style.left=(ox+e.clientX-sx)+'px';
    el.style.top=(oy+e.clientY-sy)+'px';
  });
  document.addEventListener('mouseup',()=>{drag=false;el.classList.remove('dragging');});
}
// Tooltip sidebar
const sTooltip = document.createElement('div');
sTooltip.className = 's-tooltip';
document.body.appendChild(sTooltip);

document.querySelectorAll('.s-item[data-label]').forEach(item => {
  item.addEventListener('mouseenter', e => {
    const r = item.getBoundingClientRect();
    sTooltip.textContent = item.getAttribute('data-label');
    sTooltip.style.left = (r.right + 10) + 'px';
    sTooltip.style.top  = (r.top + r.height/2) + 'px';
    sTooltip.style.transform = 'translateY(-50%)';
    sTooltip.classList.add('visible');
  });
  item.addEventListener('mouseleave', () => {
    sTooltip.classList.remove('visible');
  });
});

document.addEventListener('DOMContentLoaded',()=>{
  const mp=document.getElementById('mailPopupWindow');
  const mh=document.getElementById('mailPopupDragHandle');
  if(mp&&mh)makeDraggable(mp,mh);
  const rp=document.getElementById('replyModal');
  const rh=document.getElementById('replyDragHandle');
  if(rp&&rh)makeDraggable(rp,rh);
  document.getElementById('btnCloseMailPopup')?.addEventListener('click',()=>mp?.classList.add('hidden'));
  document.getElementById('btnCloseReply')?.addEventListener('click',()=>rp?.classList.add('hidden'));
  document.getElementById('btnCompact')?.addEventListener('click', async () => {
    await window.electronAPI?.toggleCompact();
  });
  // Drag & drop allegati
  const dz=document.getElementById('replyDropZone');
  const ov=document.getElementById('replyDropOverlay');
  if(dz){
    dz.addEventListener('dragover',e=>{e.preventDefault();ov?.classList.add('visible');});
    dz.addEventListener('dragleave',e=>{if(!dz.contains(e.relatedTarget))ov?.classList.remove('visible');});
    dz.addEventListener('drop',async e=>{
      e.preventDefault();ov?.classList.remove('visible');
      for(const file of Array.from(e.dataTransfer.files||[])){
        const reader=new FileReader();
        reader.onload=ev=>{
          const b64=ev.target.result.split(',')[1];
          if(typeof replyAttachments!=='undefined'){
            replyAttachments.push({name:file.name,data_b64:b64,type:file.type||'application/octet-stream',size:file.size});
            if(typeof renderReplyAttachments==='function')renderReplyAttachments();
          }
        };
        reader.readAsDataURL(file);
      }
    });
  }
});

// ══ SNOOZE + CONTEXT MENU ══════════════════════════════════════
(function(){
  const T = (key, it) => (window.i18n && window.i18n.t) ? window.i18n.t(key, it) : it;
  const ctxMenu = document.getElementById('mailContextMenu');
  const snoozeCustomOverlay = document.getElementById('snoozeCustomOverlay');
  const snoozeCustomDt = document.getElementById('snoozeCustomDt');
  const snoozeCustomConfirm = document.getElementById('snoozeCustomConfirm');
  const snoozeCustomCancel = document.getElementById('snoozeCustomCancel');
  const snoozeCustomClose = document.getElementById('snoozeCustomClose');

  let ctxTarget = null; // { accountId, uid, folder, subject, sender, element }
  let snoozedUids = new Set();
  let viewingSnoozed = false;

  function getActiveAccountId(){
    const sel = document.getElementById('accountSelect');
    return sel ? parseInt(sel.value) : null;
  }
  function getActiveFolder(){
    return window.currentFolder || 'INBOX';
  }

  // Preset snooze → timestamp Unix
  function snoozePresetTs(preset){
    const d = new Date();
    switch(preset){
      case '1h':       d.setHours(d.getHours()+1); break;
      case '3h':       d.setHours(d.getHours()+3); break;
      case 'tonight':  d.setHours(18,0,0,0); if(d < new Date()) d.setDate(d.getDate()+1); break;
      case 'tomorrow': d.setDate(d.getDate()+1); d.setHours(8,0,0,0); break;
      case 'monday': {
        const day = d.getDay();
        const diff = (8 - day) % 7 || 7;
        d.setDate(d.getDate()+diff); d.setHours(8,0,0,0); break;
      }
      case 'nextweek': d.setDate(d.getDate()+7); d.setHours(8,0,0,0); break;
    }
    return Math.floor(d.getTime()/1000);
  }

  async function applySnooze(wakeAtTs){
    if(!ctxTarget) return;
    try {
      const r = await fetch(`${window.GIGAMAIL_API}/snooze`, {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({
          account_id: ctxTarget.accountId,
          mail_uid: ctxTarget.uid,
          folder: ctxTarget.folder,
          subject: ctxTarget.subject,
          sender: ctxTarget.sender,
          wake_at: wakeAtTs
        })
      });
      const d = await r.json();
      if(d.success){
        const wakeStr = new Date(wakeAtTs*1000).toLocaleString((window.i18n && window.i18n.locale) || 'it-IT', {
          day:'2-digit', month:'short', hour:'2-digit', minute:'2-digit'
        });
        // toast
        if(window.showToast) window.showToast(T('win_snoozed_until', '💤 Snoozed fino a {time}').replace('{time}', wakeStr), 'success');
        // ricarica lista
        snoozedUids.add(String(ctxTarget.uid));
        if(ctxTarget.element) ctxTarget.element.style.display = 'none';
      } else {
        alert(T('win_snooze_error', 'Errore snooze') + ': ' + (d.error||T('win_unknown', 'sconosciuto')));
      }
    } catch(e) {
      alert(T('win_snooze_error', 'Errore snooze') + ': ' + e.message);
    }
    hideMenu();
  }

  async function refreshSnoozedUids(){
    const accId = getActiveAccountId();
    const folder = getActiveFolder();
    if(!accId) return;
    try {
      const r = await fetch(`${window.GIGAMAIL_API}/snooze/snoozed_uids?account_id=${accId}&folder=${encodeURIComponent(folder)}`);
      const d = await r.json();
      snoozedUids = new Set((d.uids||[]).map(String));
      applySnoozedFilterToList();
    } catch(e){}
  }

  function applySnoozedFilterToList(){
    document.querySelectorAll('.mail-item').forEach(item => {
      const uid = item.getAttribute('data-id');
      if(!uid) return;
      if(viewingSnoozed){
        item.style.display = snoozedUids.has(uid) ? '' : 'none';
      } else {
        item.style.display = snoozedUids.has(uid) ? 'none' : '';
      }
    });
  }

  // Click destro su mail item
  document.addEventListener('contextmenu', (e) => {
    const item = e.target.closest('.mail-item');
    if(!item) return;
    e.preventDefault();
    const uid = item.getAttribute('data-id');
    const folder = item.getAttribute('data-folder') || getActiveFolder();
    const accountId = parseInt(item.getAttribute('data-account-id')) || getActiveAccountId();
    const subject = item.querySelector('.mail-subject')?.textContent || '';
    const sender = item.querySelector('.mail-sender')?.textContent || '';
    ctxTarget = {
      accountId: accountId,
      uid: uid,
      folder: folder,
      subject, sender,
      element: item
    };
    ctxMenu.style.left = e.clientX + 'px';
    ctxMenu.style.top = e.clientY + 'px';
    ctxMenu.classList.remove('hidden');
    // chiudi submenu
    ctxMenu.querySelectorAll('.ctx-submenu').forEach(s => s.style.display = '');
  });

  // Chiudi context menu
  function hideMenu(){ ctxMenu.classList.add('hidden'); }
  document.addEventListener('click', e => {
    if(!ctxMenu.contains(e.target)) hideMenu();
  });
  document.addEventListener('scroll', hideMenu, true);

  // Click su voce menu
  ctxMenu.addEventListener('click', async e => {
    const btn = e.target.closest('.ctx-item');
    if(!btn) return;
    const snooze = btn.getAttribute('data-snooze');
    const action = btn.getAttribute('data-action');

    if(snooze){
      if(snooze === 'custom'){
        const now = new Date(Date.now() + 3600*1000); // default +1h
        snoozeCustomDt.value = now.toISOString().slice(0,16);
        snoozeCustomOverlay.classList.remove('hidden');
      } else {
        applySnooze(snoozePresetTs(snooze));
      }
      return;
    }

    if(action === 'open-popup'){
      if(ctxTarget?.element){
        // simula doppio click
        const evt = new MouseEvent('dblclick', { bubbles: true, cancelable: true, view: window });
        ctxTarget.element.dispatchEvent(evt);
      }
      hideMenu();
    }else if(action === 'mark-read' || action === 'mark-unread'){
      const id = ctxTarget?.uid;
      const folder = ctxTarget?.folder || 'inbox';
      const accId = ctxTarget?.accountId;
      if(id){
        const endpoint = action === 'mark-read' ? 'read' : 'unread';
        let url = `${window.GIGAMAIL_API}/mail/${encodeURIComponent(id)}/${endpoint}`;
        const params = [];
        if(accId) params.push(`account_id=${accId}`);
        if(folder) params.push(`folder=${encodeURIComponent(folder)}`);
        if(params.length) url += '?' + params.join('&');
        fetch(url, { method:'POST' })
          .then(r => r.json())
          .then(() => {
            if(ctxTarget?.element){
              ctxTarget.element.classList.toggle('unread', action === 'mark-unread');
            }
          })
          .catch(e => console.error('[MARK READ/UNREAD]', e));
      }
      hideMenu();
    } else if(action === 'delete'){
      if(ctxTarget?.element) ctxTarget.element.querySelector('.mail-delete-btn')?.click();
      hideMenu();
    }
  });

  // Custom datetime picker
  snoozeCustomClose?.addEventListener('click', () => snoozeCustomOverlay.classList.add('hidden'));
  snoozeCustomCancel?.addEventListener('click', () => snoozeCustomOverlay.classList.add('hidden'));
  snoozeCustomConfirm?.addEventListener('click', () => {
    const dt = snoozeCustomDt.value;
    if(!dt){ alert(T('win_pick_date_time', 'Seleziona data e ora')); return; }
    const ts = Math.floor(new Date(dt).getTime()/1000);
    if(ts <= Math.floor(Date.now()/1000)){ alert(T('win_date_in_past', 'Data nel passato')); return; }
    snoozeCustomOverlay.classList.add('hidden');
    applySnooze(ts);
  });

  // Tab "Snoozed" (💤)
  document.getElementById('btnShowSnoozed')?.addEventListener('click', async () => {
    viewingSnoozed = !viewingSnoozed;
    document.getElementById('btnShowSnoozed').classList.toggle('active', viewingSnoozed);
    document.getElementById('btnShowInboxTab')?.classList.toggle('active', !viewingSnoozed);
    await refreshSnoozedUids();
  });

  // Refresh snoozed UIDs ogni volta che la lista mail cambia
  // Hook: osserva mailList per cambiamenti
  const mailList = document.getElementById('mailList');
  if(mailList){
    const obs = new MutationObserver(() => refreshSnoozedUids());
    obs.observe(mailList, { childList: true });
  }
  // E al boot
  setTimeout(refreshSnoozedUids, 2000);
  // E ogni minuto (per vedere mail risvegliate)
  setInterval(refreshSnoozedUids, 60000);
})();
// Buttons that used to carry onclick="..." in the page: the CSP forbids
// inline handlers, so they are wired here.
(function () {
  const on = (id, fn) => { const el = document.getElementById(id); if (el) el.addEventListener('click', fn); };
  on('btnWinMin', () => window.electronAPI?.minimizeWindow());
  on('btnWinMax', () => window.electronAPI?.maximizeWindow());
  on('btnWinClose', () => window.electronAPI?.closeWindow());
  on('langSwitch', () => window.i18n && window.i18n.toggleLang());
  on('btnOnboarding', () => window.openOnboarding && window.openOnboarding());
  on('btnLoginOverlayX', () => document.getElementById('loginOverlay').classList.add('hidden'));
})();
