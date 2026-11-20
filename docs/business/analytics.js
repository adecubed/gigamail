import {analyticsConfig} from './analytics-config.js';
// Visit counter for the whole site (every page loads this module), as on
// nerine.io: anonymous events to our backend.
// Contatore visite in stile nerine.io: eventi anonimi al backend, niente
// cookie, niente contatori locali, niente campi del form. Parte solo in HTTPS
// sui domini di produzione e rispetta Do Not Track / Global Privacy Control.
export function analyticsAllowed(config, win=window){
 if(win.location.protocol!=='https:' || !config.productionHosts.includes(win.location.hostname))return false;
 if(win.navigator.globalPrivacyControl===true || win.navigator.doNotTrack==='1')return false;
 return true;
}
// Manda un evento al backend. Tipi accettati dal server: visita, contatti_lasciati.
export function track(type, extra, config=analyticsConfig, win=window){
 const url=config.eventsEndpoint?.trim();
 if(!url || !analyticsAllowed(config, win))return false;
 const body={type, site:config.site, ...(extra||{})};
 try{win.fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),keepalive:true}).catch(()=>{});}catch{return false;}
 return true;
}
// Kind of device and system, from the user agent: a short name each,
// nothing that tells one visitor from another.
export function deviceInfo(nav){
 const ua=(nav&&nav.userAgent)||'';
 const touch=((nav&&nav.maxTouchPoints)||0)>1;
 let os='other';
 if(/iPhone|iPad|iPod/i.test(ua))os='ios';
 else if(/Android/i.test(ua))os='android';
 else if(/CrOS/i.test(ua))os='chromeos';
 else if(/Windows/i.test(ua))os='windows';
 else if(/Macintosh|Mac OS X/i.test(ua))os=touch?'ios':'mac';   // iPadOS says Macintosh
 else if(/Linux/i.test(ua))os='linux';
 let device='desktop';
 if(os==='ios')device=/iPhone|iPod/i.test(ua)?'mobile':'tablet';
 else if(os==='android')device=/Mobile/i.test(ua)?'mobile':'tablet';
 return {device, os};
}
// Where this visit came from: the utm tags of the address, else the site
// that linked here. Moving between pages of gigamail.ai keeps the source
// of the page the visitor landed on, for that tab only (sessionStorage),
// so a download click two pages later still counts for that source.
const LANDING_KEY='gigamail-landing';
export function landing(config=analyticsConfig, win=window, doc=document){
 let params;try{params=new URL(win.location.href).searchParams;}catch{params=new URLSearchParams('');}
 let referrer='';try{referrer=doc.referrer?new URL(doc.referrer).hostname:'';}catch{}
 const here={referrer, utm_source:(params.get('utm_source')||'').slice(0,40), utm_campaign:(params.get('utm_campaign')||'').slice(0,40)};
 const inside=config.productionHosts.includes(referrer);
 try{
  if(inside && !here.utm_source){const saved=JSON.parse(win.sessionStorage.getItem(LANDING_KEY)||'null');if(saved)return saved;}
  else win.sessionStorage.setItem(LANDING_KEY,JSON.stringify(here));
 }catch{}
 return here;
}
let visitTracked=false;
export function trackVisit(config=analyticsConfig, win=window, doc=document){
 if(visitTracked)return false;visitTracked=true;
 const country=(win.navigator.language||'').slice(0,5);   // regione approssimata dalla lingua del browser
 return track('visita',{...landing(config,win,doc), ...deviceInfo(win.navigator), country},config,win);
}
// Beacon Cloudflare Web Analytics, facoltativo: parte solo con un token valido.
export function installAnalytics(config, win=window, doc=document){
 const token=config.cloudflareToken?.trim();
 if(!token || !/^[a-f0-9]{32}$/i.test(token))return false;
 if(!analyticsAllowed(config, win))return false;
 if(doc.querySelector('script[src*="static.cloudflareinsights.com/beacon.min.js"]'))return false;
 const script=doc.createElement('script');script.src='https://static.cloudflareinsights.com/beacon.min.js';script.defer=true;
 script.setAttribute('data-cf-beacon',JSON.stringify({token}));doc.head.append(script);return true;
}
// Download clicks: which installer, nothing about who. Each link to a
// release file of the repo sends one 'download' event with the file's kind
// (the backend accepts only these names); the release page itself counts as
// 'release-page'. One listener on the document covers every page and the
// hero button, whose href home.js swaps for the visitor's platform. The
// browser follows the link as usual: keepalive lets the event finish.
const RELEASES = /^https:\/\/github\.com\/adecubed\/gigamail\/releases\b/;
export function downloadKind(href){
 if(!RELEASES.test(href||''))return '';
 const file=(href.split('?')[0].split('/').pop()||'');
 if(/\.exe$/i.test(file))return 'win';
 if(/arm64\.dmg$/i.test(file))return 'mac-arm';
 if(/x64\.dmg$/i.test(file))return 'mac-intel';
 if(/\.deb$/i.test(file))return 'linux-deb';
 if(/\.AppImage$/i.test(file))return 'linux-appimage';
 return 'release-page';
}
export function trackDownloads(config=analyticsConfig, win=window, doc=document){
 doc.addEventListener('click',(e)=>{
  const a=e.target&&e.target.closest?e.target.closest('a[href]'):null;
  const kind=a?downloadKind(a.href):'';
  if(kind)track('download',{text:kind, ...landing(config,win,doc), ...deviceInfo(win.navigator)},config,win);
 },true);
}
if(typeof window!=='undefined'){
 trackVisit();
 trackDownloads();
 installAnalytics(analyticsConfig);
}
