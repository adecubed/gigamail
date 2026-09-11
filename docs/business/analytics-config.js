// Contatore visite: lo stesso backend che conta il sito nerine.io.
// La pagina manda gli eventi (visita, contatti_lasciati) in POST a
// eventsEndpoint con site='gigamail'. Il riepilogo si legge da:
//   https://adecubed-sofia.onrender.com/stats?site=gigamail
//   https://adecubed-sofia.onrender.com/stats?site=gigamail&days=7&format=text   (per Sofia)
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
