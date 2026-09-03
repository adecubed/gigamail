// features.js — la console mostra solo cio' che il backend sa fare.
//
// All'avvio legge /openapi.json dal backend (FastAPI lo espone gratis) e
// ogni bottone dichiara l'endpoint che gli serve con data-requires="/path":
// se il path non esiste, il bottone sparisce (classe .hidden). Cosi' una
// funzione senza backend — marketing, voce, TTS, riassunto — non resta li'
// a restituire 404, e riappare da sola il giorno che il backend la offre.
// I path usano la forma template di OpenAPI: "/mail/{message_id}/summary".
//
// Se il backend non risponde, non si nasconde nulla: meglio un 404 di una
// console che sembra vuota per un hiccup di rete.
const Features = (() => {
  let paths = null;   // null = sconosciuto

  async function load(apiBase) {
    try {
      const r = await fetch(`${apiBase}/openapi.json`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const spec = await r.json();
      paths = new Set(Object.keys(spec.paths || {}));
    } catch (_) {
      paths = null;
    }
    return paths;
  }

  function has(path) {
    return paths === null ? true : paths.has(path);
  }

  function missing(list) {
    return (list || []).filter((p) => !has(p));
  }

  /** Applica il gate agli elementi con data-requires dentro `root`. */
  function apply(root) {
    (root || document).querySelectorAll('[data-requires]').forEach((el) => {
      const need = String(el.dataset.requires || '').split(/\s+/).filter(Boolean);
      const lacking = missing(need);
      el.classList.toggle('hidden', lacking.length > 0);
      if (lacking.length) el.setAttribute('data-feature-missing', lacking.join(' '));
      else el.removeAttribute('data-feature-missing');
    });
  }

  return { load, has, missing, apply, get known() { return paths !== null; } };
})();
if (typeof window !== 'undefined') window.Features = Features;
if (typeof module !== 'undefined' && module.exports) module.exports = Features;
