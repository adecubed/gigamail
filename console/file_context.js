// file_context.js — a file dropped on the AI instruction becomes context
// for the draft: its text goes to the backend apart from the instruction.
// The windows used to call /office/upload, which the backend never had:
// the badge showed the file's name and the draft was written without it.
(function () {
  // What the backend said, as one line for the placeholder.
  function errorText(data, status) {
    const d = data && data.detail;
    if (typeof d === 'string' && d) return d;
    if (Array.isArray(d) && d.length && d[0].msg) return String(d[0].msg);
    return `HTTP ${status}`;
  }

  // {ok, name, text, chars, type} or {ok: false, error}. Never throws.
  async function extract(api, file, fetchFn = (typeof fetch !== 'undefined' ? fetch : null)) {
    try {
      const form = new FormData();
      form.append('file', file);
      const r = await fetchFn(`${api}/files/extract_text`, { method: 'POST', body: form });
      let data = {};
      try { data = await r.json(); } catch { data = {}; }
      if (!r.ok) return { ok: false, error: errorText(data, r.status) };
      const text = String((data && data.text) || '');
      if (!text.trim()) return { ok: false, error: errorText(data, r.status) };
      return { ok: true, name: data.name || file.name || 'file', text,
               chars: data.chars || text.length, type: data.type || '' };
    } catch (e) {
      return { ok: false, error: String((e && e.message) || e) };
    }
  }

  // "price_list.pdf · 12345 caratteri"
  function badgeText(ctx, T) {
    const t = typeof T === 'function' ? T : (_k, fb) => fb;
    return `${ctx.name} · ${ctx.chars} ${t('app_characters', 'caratteri')}`;
  }

  const GMFileContext = { extract, badgeText, errorText };
  if (typeof window !== 'undefined') window.GMFileContext = GMFileContext;
  if (typeof module !== 'undefined' && module.exports) module.exports = GMFileContext;
})();
