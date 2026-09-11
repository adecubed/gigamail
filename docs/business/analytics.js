import {analyticsConfig} from './analytics-config.js';
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
let visitTracked=false;
export function trackVisit(config=analyticsConfig, win=window, doc=document){
 if(visitTracked)return false;visitTracked=true;
 let referrer='';try{referrer=doc.referrer?new URL(doc.referrer).hostname:'';}catch{}
 const country=(win.navigator.language||'').slice(0,5);   // regione approssimata dalla lingua del browser
 return track('visita',{referrer, country},config,win);
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
trackVisit();
installAnalytics(analyticsConfig);
