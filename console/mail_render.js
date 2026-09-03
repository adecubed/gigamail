// mail_render.js — L'UNICA pipeline che porta l'HTML di una mail dentro
// un iframe. Usata dalla finestra principale (renderer.js) e dalla finestra
// mail (mail_window.html): prima erano due copie con regole diverse.
//
// Difesa a strati, ognuno sufficiente da solo:
//   1. sanitizeHtml: parsing strutturale (DOMParser), via script/iframe/
//      object/form/meta/base/link, via ogni attributo on*, via javascript:
//      e vbscript: negli URL, via CSS con expression()/behavior.
//   2. L'iframe e' sandbox SENZA allow-scripts e senza allow-popups: anche
//      cio' che sfuggisse al punto 1 non esegue e non apre finestre.
//   3. Il documento scritto porta una meta-CSP propria (default-src 'none').
//   4. I click sui link sono intercettati per delega e vanno a openExternal:
//      un link non puo' navigare l'iframe verso un sito remoto.
// allow-same-origin resta perche' serve al padre per misurare l'altezza e
// intercettare i click; senza allow-scripts il contenuto non puo' usarla.
(function () {
  const BLANK_GIF = 'data:image/gif;base64,R0lGODlhAQABAAAAACH5BAEKAAEALAAAAAABAAEAAAICTAEAOw==';
  const DROP_TAGS = [
    'script', 'noscript', 'template', 'iframe', 'frame', 'frameset', 'portal',
    'object', 'embed', 'applet', 'base', 'meta', 'link', 'form', 'input',
    'button', 'textarea', 'select', 'option', 'audio', 'video', 'source', 'track',
  ];
  const URL_ATTRS = ['href', 'src', 'srcset', 'action', 'formaction', 'poster',
    'background', 'data', 'xlink:href', 'ping', 'codebase', 'cite', 'longdesc', 'usemap'];
  const IFRAME_CSP = "default-src 'none'; img-src http: https: data: blob:; "
    + "style-src 'unsafe-inline'; font-src http: https: data:; form-action 'none'; base-uri 'none'";

  function _unsafeUrl(value) {
    // Toglie controlli/spazi che Chromium ignora nel parsing ("java\tscript:").
    const s = String(value || '').replace(/[\x00-\x20\x7f]+/g, '').toLowerCase(); // eslint-disable-line no-control-regex -- voluto: un tab dentro 'javascript:' deve sparire
    return s.startsWith('javascript:') || s.startsWith('vbscript:')
      || s.startsWith('data:text/html') || s.startsWith('data:image/svg+xml') || s.startsWith('data:application');
  }

  function _stripCid(v) {
    return decodeURIComponent(String(v || '').trim().replace(/^cid:/i, '')).replace(/[<>]/g, '');
  }

  // Trova l'allegato che corrisponde a un Content-ID: per contentId esatto,
  // poi per nome file uguale alla parte prima della @, poi per inclusione;
  // con un solo allegato e' quello.
  function matchAttachment(cid, attachments) {
    const atts = Array.isArray(attachments) ? attachments : [];
    const clean = _stripCid(cid);
    const guess = (clean.split('@')[0] || '').toLowerCase();
    return atts.find((a) => String(a.contentId || '').replace(/[<>]/g, '') === clean)
      || atts.find((a) => String(a.name || '').toLowerCase() === guess)
      || (guess && atts.find((a) => String(a.name || '').toLowerCase().includes(guess)))
      || (atts.length === 1 ? atts[0] : null)
      || null;
  }

  /**
   * Ritorna un documento HTML completo, sicuro, pronto per document.write.
   * @param {string} html
   * @param {{resolveCid?: (cid: string) => string|null}} [opts]
   */
  function sanitizeHtml(html, opts) {
    const resolveCid = (opts && opts.resolveCid) || null;
    const doc = new DOMParser().parseFromString(String(html || ''), 'text/html');

    // <style> nel <head> vanno tenuti (layout delle newsletter): li salvo
    // prima di ripulire il resto della head.
    const headStyles = Array.from(doc.head ? doc.head.querySelectorAll('style') : []);

    doc.querySelectorAll(DROP_TAGS.join(',')).forEach((el) => el.remove());

    doc.querySelectorAll('*').forEach((el) => {
      for (const attr of Array.from(el.attributes)) {
        const name = attr.name.toLowerCase();
        if (name.startsWith('on')) { el.removeAttribute(attr.name); continue; }
        if (URL_ATTRS.includes(name)) {
          const v = attr.value;
          if (/^\s*cid:/i.test(v)) {
            const resolved = resolveCid ? resolveCid(_stripCid(v)) : null;
            if (resolved) el.setAttribute(attr.name, resolved);
            else if (name === 'src') el.setAttribute(attr.name, BLANK_GIF);
            else el.removeAttribute(attr.name);
            continue;
          }
          if (name === 'srcset' ? /javascript:|vbscript:|cid:/i.test(v) : _unsafeUrl(v)) {
            el.removeAttribute(attr.name);
          }
        }
        if (name === 'style' && /expression\s*\(|javascript:|vbscript:|behavior\s*:|-moz-binding/i.test(attr.value)) {
          el.removeAttribute('style');
        }
      }
      if (el.tagName === 'A') {
        el.setAttribute('target', '_blank');
        el.setAttribute('rel', 'noopener noreferrer');
      }
    });

    // <style> con expression()/javascript: (IE-era, ma costano zero)
    doc.querySelectorAll('style').forEach((s) => {
      if (/expression\s*\(|javascript:|vbscript:|behavior\s*:|-moz-binding|@import/i.test(s.textContent || '')) s.remove();
    });

    const head = doc.createElement('head');
    const charset = doc.createElement('meta');
    charset.setAttribute('charset', 'utf-8');
    const csp = doc.createElement('meta');
    csp.setAttribute('http-equiv', 'Content-Security-Policy');
    csp.setAttribute('content', IFRAME_CSP);
    head.appendChild(charset);
    head.appendChild(csp);
    headStyles.forEach((s) => { if (s.isConnected) head.appendChild(s); });
    const body = doc.body || doc.createElement('body');
    return '<!DOCTYPE html><html>' + head.outerHTML + body.outerHTML + '</html>';
  }

  /**
   * Monta l'iframe sandboxed con l'HTML sanitizzato dentro `container`.
   * @param {HTMLElement} container
   * @param {string} html
   * @param {{
   *   attachments?: Array<{name?: string, contentId?: string}>,
   *   attachmentUrl?: (att: object) => string,
   *   openExternal?: (href: string) => void,
   *   autoHeight?: boolean,
   *   minHeight?: number,
   * }} [opts]
   * @returns {HTMLIFrameElement}
   */
  function renderMailHtml(container, html, opts) {
    const o = opts || {};
    const attachments = o.attachments || [];
    const resolveCid = (cid) => {
      const att = matchAttachment(cid, attachments);
      return att && o.attachmentUrl ? o.attachmentUrl(att) : null;
    };
    const safe = sanitizeHtml(html, { resolveCid });

    const iframe = document.createElement('iframe');
    iframe.setAttribute('sandbox', 'allow-same-origin');
    iframe.setAttribute('referrerpolicy', 'no-referrer');
    iframe.className = 'mail-html-frame';
    iframe.style.cssText = o.autoHeight
      ? `width:100%;border:none;min-height:${o.minHeight || 400}px;display:block;background:#fff;`
      : 'width:100%;height:100%;border:none;display:block;background:#fff;';
    if (o.autoHeight) iframe.setAttribute('scrolling', 'no');
    container.appendChild(iframe);

    const iDoc = iframe.contentDocument || (iframe.contentWindow && iframe.contentWindow.document);
    if (!iDoc) return iframe;
    iDoc.open();
    iDoc.write(safe);
    iDoc.close();

    // Delega sul documento: prende anche link aggiunti da CSS-hover o annidati.
    iDoc.addEventListener('click', (e) => {
      const a = e.target && e.target.closest ? e.target.closest('a[href]') : null;
      if (!a) return;
      e.preventDefault();
      const href = a.getAttribute('href') || '';
      if (/^(https?:|mailto:)/i.test(href.trim()) && o.openExternal) o.openExternal(href.trim());
    }, true);
    // Nessun submit/navigazione dall'interno: sandbox gia' lo vieta, ma
    // un preventDefault esplicito non costa nulla.
    iDoc.addEventListener('submit', (e) => e.preventDefault(), true);

    if (o.autoHeight) {
      const fit = () => {
        try {
          const h = (iDoc.body && iDoc.body.scrollHeight) || o.minHeight || 400;
          iframe.style.height = Math.min(h + 20, 12400) + 'px';
        } catch (_) { /* iframe gia' rimosso */ }
      };
      setTimeout(fit, 200);
      setTimeout(fit, 1200);   // immagini arrivate dopo
    }
    return iframe;
  }

  /** Testo semplice da HTML di posta, per citare/inoltrare. Documento inerte:
   *  niente esecuzione di script o handler, niente caricamento di risorse.
   *  Condiviso da finestra principale e finestra mail. */
  function htmlToText(html) {
    const doc = new DOMParser().parseFromString(String(html || ''), 'text/html');
    doc.querySelectorAll('style, script, head, meta, link, noscript, template').forEach((el) => el.remove());
    doc.querySelectorAll('br').forEach((el) => el.replaceWith('\n'));
    doc.querySelectorAll('p, div, li, tr, h1, h2, h3, h4, h5, h6, blockquote, pre').forEach((el) => el.append('\n'));
    return (doc.body ? doc.body.textContent : '').replace(/[ \t]+\n/g, '\n').replace(/\n{3,}/g, '\n\n').trim();
  }

  const MailRender = { sanitizeHtml, renderMailHtml, matchAttachment, htmlToText, BLANK_GIF, IFRAME_CSP };
  if (typeof window !== 'undefined') window.MailRender = MailRender;
  if (typeof module !== 'undefined' && module.exports) module.exports = MailRender;
})();
