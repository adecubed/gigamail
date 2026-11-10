// attachment_drag.js — an attachment of a received mail, dragged onto a mail
// being written (new mail, reply window, reply box), is attached to it.
//
// The drag carries a reference, never the bytes: which message, which file.
// Whoever receives the drop asks the backend for the file with its own
// address of the backend, so a drag coming from another program cannot make
// the console fetch a URL of its choosing. The windows are separate
// documents: a reference is all that crosses between them.
(function () {
  'use strict';

  const TYPE = 'application/x-gigamail-attachment';

  function isExecutable(name) {
    const guard = (typeof window !== 'undefined' && window.GMAttachmentGuard)
      || (typeof require === 'function' ? require('./attachment_guard') : null);
    return !!(guard && guard.isExecutableName(name));
  }

  /** The reference as it travels, or null when it names no attachment. */
  function clean(ref) {
    if (!ref || typeof ref !== 'object') return null;
    const id = typeof ref.id === 'string' ? ref.id : '';
    const name = typeof ref.name === 'string' ? ref.name : '';
    if (!id || !name) return null;
    const account = parseInt(ref.accountId, 10);
    return {
      id, name,
      accountId: Number.isInteger(account) && account > 0 ? account : null,
      folder: typeof ref.folder === 'string' ? ref.folder : '',
      type: typeof ref.type === 'string' ? ref.type : '',
    };
  }

  /** Makes a chip of a received mail draggable. A file that runs a program
   *  stays where it is: the backend releases one only for "Save as". */
  function makeSource(chip, ref) {
    const data = clean(ref);
    if (!chip || !data || isExecutable(data.name)) return false;
    chip.setAttribute('draggable', 'true');
    chip.addEventListener('dragstart', (e) => {
      if (!e.dataTransfer) return;
      e.dataTransfer.setData(TYPE, JSON.stringify(data));
      e.dataTransfer.effectAllowed = 'copy';
    });
    return true;
  }

  function carries(e) {
    return !!(e && e.dataTransfer && Array.from(e.dataTransfer.types || []).includes(TYPE));
  }

  /** The reference in a drop. Read it inside the drop handler: the data of
   *  a drag is gone once the handler returns. */
  function refFrom(e) {
    if (!carries(e)) return null;
    try { return clean(JSON.parse(e.dataTransfer.getData(TYPE))); } catch { return null; }
  }

  function urlFor(api, ref) {
    let url = `${api}/mail/${encodeURIComponent(ref.id)}/attachment/${encodeURIComponent(ref.name)}`;
    const params = [];
    if (ref.accountId) params.push(`account_id=${ref.accountId}`);
    if (ref.folder) params.push(`folder=${encodeURIComponent(ref.folder)}`);
    if (params.length) url += `?${params.join('&')}`;
    return url;
  }

  function toBase64(bytes) {
    let bin = '';
    for (let i = 0; i < bytes.length; i += 0x8000) {
      bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
    }
    return btoa(bin);
  }

  /** Fetches the file a reference names: {name, data_b64, type, size}, the
   *  shape every compose window keeps its attachments in. */
  async function fetchFile(api, ref, fetchFn) {
    const data = clean(ref);
    if (!data || isExecutable(data.name)) throw new Error('not an attachment that can be dragged');
    const r = await (fetchFn || fetch)(urlFor(api, data));
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const bytes = new Uint8Array(await r.arrayBuffer());
    const declared = (r.headers && r.headers.get && r.headers.get('content-type')) || '';
    return {
      name: data.name,
      data_b64: toBase64(bytes),
      type: declared.split(';')[0].trim() || data.type || 'application/octet-stream',
      size: bytes.length,
    };
  }

  /** For a drop handler: true when the drop was an attachment of a mail
   *  (and is being taken care of), false when it is something else (files
   *  from the desktop) and the caller goes on as before. */
  function takeDrop(e, api, onFile, onError) {
    if (!carries(e)) return false;
    const ref = refFrom(e);
    if (!ref) return true;
    fetchFile(api, ref).then(onFile).catch((err) => { if (onError) onError(ref.name, err); });
    return true;
  }

  const AttachmentDrag = { TYPE, makeSource, carries, refFrom, urlFor, fetchFile, takeDrop };
  if (typeof module !== 'undefined' && module.exports) module.exports = AttachmentDrag;
  if (typeof window !== 'undefined') window.GMAttachmentDrag = AttachmentDrag;
})();
