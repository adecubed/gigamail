import {demoConfig} from './config.js';
import {track} from './analytics.js';
const $=s=>document.querySelector(s),reducedQuery=matchMedia('(prefers-reduced-motion: reduce)');let paused=false,disposeScene;
function syncMotion(){document.body.classList.toggle('motion-reduced',reducedQuery.matches);$('#motion-toggle').hidden=reducedQuery.matches;window.dispatchEvent(new Event('scene-state'));}
syncMotion();reducedQuery.addEventListener('change',syncMotion);
$('#motion-toggle').addEventListener('click',()=>{paused=!paused;$('#motion-toggle').textContent=paused?'Riprendi animazione':'Pausa animazione';$('#motion-toggle').setAttribute('aria-pressed',String(paused));window.dispatchEvent(new Event('scene-state'));});
const details=[['CONTESTO','La tua azienda','Clienti, preventivi, documenti e appuntamenti: informazioni collegate al lavoro che devi svolgere.'],['PERSONE','Clienti','Richieste, preferenze e conversazioni precedenti, per rispondere con il contesto giusto.'],['COMMERCIALE','Preventivi','Ritrova le proposte inviate e le risposte ricevute. Prepara il prossimo follow-up.'],['DOCUMENTI','Allegati e pratiche','Consulta i documenti disponibili e verifica quali informazioni non risultano nei file letti.'],['CONOSCENZA','Listini e condizioni','Il tuo agente usa i file di riferimento che hai scelto per preparare risposte coerenti.'],['RELAZIONI','Fornitori','Ricostruisci richieste, preventivi e aggiornamenti dalle conversazioni.'],['CALENDARIO','Appuntamenti','Consulta appuntamenti e disponibilità del calendario supportato dal provider collegato.'],['CONVERSAZIONI','Email e storico','La posta collega richieste, persone, allegati e decisioni passate.']];let activeNode;
document.querySelectorAll('[data-node]').forEach(button=>{button.setAttribute('aria-pressed','false');button.setAttribute('aria-controls','node-info');button.addEventListener('click',()=>{activeNode?.setAttribute('aria-pressed','false');activeNode=button;button.setAttribute('aria-pressed','true');const d=details[Number(button.dataset.node)];$('#detail-type').textContent=d[0];$('#detail-title').textContent=d[1];$('#detail-body').textContent=d[2];$('#node-info').hidden=false;$('#close-node').focus({preventScroll:true});});});
function closeNode(){if($('#node-info').hidden)return;$('#node-info').hidden=true;activeNode?.setAttribute('aria-pressed','false');activeNode?.focus({preventScroll:true});}$('#close-node').addEventListener('click',closeNode);document.addEventListener('keydown',e=>{if(e.key==='Escape')closeNode();});
const wait=ms=>new Promise(r=>setTimeout(r,reducedQuery.matches?0:ms));
import {scenarios} from './scenarios.js';
let selected='b2b', generation=0;
function selectScenario(key){
 selected=key;generation++;const s=scenarios[key];
 document.querySelectorAll('[data-scenario]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.scenario===key)));
 $('#scenario-prompt').textContent='“'+s.prompt+'”';$('#scenario-note').textContent=s.note;
 $('#search-results').hidden=true;$('#followup-preview').hidden=true;$('#prepare-followup').hidden=false;
 $('#run-search').hidden=false;$('#run-search').disabled=false;$('#search-status').textContent='';
}
document.querySelectorAll('[data-scenario]').forEach(b=>b.addEventListener('click',()=>selectScenario(b.dataset.scenario)));
$('#run-search').addEventListener('click',async()=>{
 const token=++generation,s=scenarios[selected],b=$('#run-search');b.disabled=true;
 $('#search-status').textContent='Ricerca nel contesto di esempio…';await wait(650);if(token!==generation)return;
 $('#search-status').textContent='Confronto conversazioni e documenti…';await wait(700);if(token!==generation)return;
 $('#result-count').textContent=s.count;$('#result-title').textContent=s.title;$('#result-filter').textContent=s.filter;
 const rows=$('#result-rows');rows.replaceChildren();s.rows.forEach(([name,detail,status])=>{
  const row=document.createElement('div');row.className='client-row';
  const avatar=document.createElement('span');avatar.className='avatar';avatar.textContent=name.split(' ').map(w=>w[0]).slice(0,2).join('');
  const title=document.createElement('strong');title.textContent=name;const desc=document.createElement('span');desc.textContent=detail;const badge=document.createElement('small');badge.textContent=status;
  row.append(avatar,title,desc,badge);rows.append(row);
 });
 $('#result-summary').textContent=`${s.rows.length} dei ${s.count} risultati di esempio`;
 $('#prepare-followup').textContent=s.action+' →';$('#draft-body').textContent=s.draft;
 $('#search-results').hidden=false;$('#search-status').textContent='Esempio completato. Nessun account reale collegato.';b.hidden=true;
});
$('#prepare-followup').addEventListener('click',()=>{$('#followup-preview').hidden=false;$('#prepare-followup').hidden=true;$('#followup-preview').focus({preventScroll:true});});
selectScenario('b2b');
$('#approve-demo').addEventListener('click',async()=>{const b=$('#approve-demo'),steps=[...$('#approval-steps').children];if(b.dataset.complete){steps.forEach((s,i)=>{s.className=i===0?'done':i===1?'current':'';});b.dataset.complete='';b.textContent='Simula la tua approvazione →';$('#approval-status').textContent='Esempio illustrativo: nessuna autenticazione o email reale.';return;}b.disabled=true;steps[1].className='done';steps[2].className='current';$('#approval-status').textContent='Nell’app, confermi con Windows Hello o Touch ID fuori dall’agente.';await wait(1400);steps[2].className='done';steps[3].className='done';$('#approval-status').textContent='Simulazione completata. Nel prodotto, solo ora viene inviata l’email approvata.';b.disabled=false;b.dataset.complete='true';b.textContent='Rivedi il processo ↺';});
$('#demo-form').addEventListener('submit',async e=>{e.preventDefault();const form=e.currentTarget,status=$('#form-status'),button=form.querySelector('button'),data=Object.fromEntries(new FormData(form));if(!demoConfig.endpoint&&!demoConfig.email){status.textContent='Il recapito per le richieste demo non è ancora configurato. Nessun dato è stato inviato.';return;}if(demoConfig.endpoint){button.disabled=true;status.textContent='Invio della richiesta…';try{const response=await fetch(demoConfig.endpoint,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data),signal:AbortSignal.timeout(15000)});if(!response.ok)throw Error();const result=await response.json();if(result.ok!==true)throw Error();status.textContent='Richiesta ricevuta. Ti ricontatteremo per la demo.';form.reset();track('contatti_lasciati');}catch{status.textContent='Invio non riuscito. Riprova tra poco: la ricezione non è stata confermata.';}finally{button.disabled=false;}}else{const body=`Nome: ${data.name}\nAzienda: ${data.agency}\nEmail: ${data.email}\nTelefono: ${data.phone||'Non indicato'}\n\nVorrei una demo di GigaMail per la mia azienda.`;location.href=`mailto:${encodeURIComponent(demoConfig.email)}?subject=${encodeURIComponent('Demo GigaMail — Business')}&body=${encodeURIComponent(body)}`;status.textContent='Completa l’invio nel tuo programma di posta. La richiesta non viene inviata automaticamente.';}});
import('./scene.js').then(({startScene})=>{disposeScene=startScene({reduced:()=>reducedQuery.matches,paused:()=>paused});}).catch(()=>{document.body.classList.add('motion-reduced');$('#motion-toggle').hidden=true;});
window.addEventListener('pagehide',e=>{if(!e.persisted)disposeScene?.();});
