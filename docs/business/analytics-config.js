// Contatore visite: lo stesso backend che conta il sito nerine.io.
// La pagina manda gli eventi (visita, contatti_lasciati) in POST a
// eventsEndpoint con site='gigamail'. Where to read the summary is not
// written here: this file is public.
// Lascia eventsEndpoint vuoto per spegnere il contatore.
//
// cloudflareToken: token pubblico di Cloudflare Web Analytics (Manage site >
// JS snippet), facoltativo. NON un token API dell'account. Vuoto = spento.
export const analyticsConfig = {
  eventsEndpoint: 'https://adecubed-sofia.onrender.com/event',
  site: 'gigamail',
  cloudflareToken: '',
  productionHosts: ['gigamail.ai', 'www.gigamail.ai']
};
