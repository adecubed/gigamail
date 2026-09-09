export const stations={
 inbox:{name:'Inbox',x:-18,z:9,color:'#f58b4b',label:'01 / ARRIVAL',title:'Every mail has a journey.',text:'A customer asks for a quote. Follow the message through GigaMail, and decide what happens next.'},
 llm:{name:'LLM',x:-7,z:9,color:'#826ade',label:'02 / UNDERSTAND',title:'Context becomes a reply.',text:'The model reads the request and uses permitted context. It can propose an action; it cannot grant itself permission.'},
 tools:{name:'Tools',x:4,z:9,color:'#428db8',label:'03 / TOOL DEPOT',title:'The right tool. The right permission.',text:'Inspect context and tool permissions before preparing the reply.'},
 draft:{name:'Draft',x:15,z:9,color:'#d6a239',label:'04 / COMPOSE',title:'A draft, ready for your decision.',text:'This is the exact reply that travels to the next checkpoint. You can edit it before sending.'},
 mode:{name:'Choose a lane',x:15,z:-3,color:'#9cb358',label:'05 / ROUTING',title:'How much autonomy?',text:'Semi-autopilot prepares a proposal. Autopilot sends only when a configured rule allows it.'},
 semi:{name:'Semi-autopilot',x:5,z:-3,color:'#db9654',label:'06 / SEMI-AUTOPILOT',title:'Prepared. Not sent.',text:'The agent has done the preparation. Sending waits for a human decision.'},
 auto:{name:'Autopilot',x:15,z:-15,color:'#65a58d',label:'06 / AUTOPILOT',title:'Permission before execution.',text:'Demo rule: quote replies to the original sender, no attachment, at most 3 sends. Anything else returns to human review.'},
 approval:{name:'Approval',x:-6,z:-3,color:'#d58e63',label:'07 / HUMAN CHECKPOINT',title:'Approve, edit, or reject.',text:'Your decision applies to this draft. An edit creates a revised proposal for approval.'},
 security:{name:'Injection lab',x:-18,z:-3,color:'#cb6460',label:'SECURITY / UNTRUSTED INPUT',title:'An email cannot rewrite the rules.',text:'Try an injected instruction. The demo keeps the instruction in quarantine and blocks unauthorized tool use.'},
 rejected:{name:'Rejected',x:-18,z:-15,color:'#ad6971',label:'OUTCOME / RETAINED',title:'Rejected. Nothing sent.',text:'The draft is retained for inspection. Rejection produces no send action.'},
 sent:{name:'Delivered',x:-4,z:-15,color:'#6baf94',label:'OUTCOME / DELIVERED',title:'A considered send.',text:'The simulated reply has arrived with its authorization recorded. No real email was sent.'}
};
const italianStations={inbox:{name:'Posta in arrivo',label:'01 / ARRIVO',title:'Ogni mail ha un viaggio.',text:'Un cliente chiede un preventivo. Segui il messaggio dentro GigaMail e decidi cosa succede dopo.'},llm:{name:'LLM',label:'02 / COMPRENDERE',title:'Il contesto diventa una risposta.',text:'Il modello legge la richiesta e usa il contesto autorizzato. Può proporre un’azione, ma non può concedersi il permesso.'},tools:{name:'Strumenti',label:'03 / DEPOSITO TOOLS',title:'Lo strumento giusto. Il permesso giusto.',text:'Controlla contesto e permessi prima di preparare la risposta.'},draft:{name:'Bozza',label:'04 / COMPOSIZIONE',title:'Una bozza pronta per la tua decisione.',text:'Questa è la risposta esatta che va al checkpoint. Puoi modificarla prima dell’invio.'},mode:{name:'Scegli una corsia',label:'05 / INSTRADAMENTO',title:'Quanta autonomia?',text:'Il semi-autopilot prepara una proposta. L’autopilot invia solo quando una regola configurata lo consente.'},semi:{name:'Semi-autopilot',label:'06 / SEMI-AUTOPILOT',title:'Preparata. Non inviata.',text:'L’agente ha completato la preparazione. L’invio attende una decisione umana.'},auto:{name:'Autopilot',label:'06 / AUTOPILOT',title:'Permesso prima dell’esecuzione.',text:'Regola demo: risposte di preventivo al mittente originale, senza allegati, massimo 3 invii. Tutto il resto torna alla revisione umana.'},approval:{name:'Approvazione',label:'07 / CHECKPOINT UMANO',title:'Approva, modifica o rifiuta.',text:'La tua decisione vale per questa bozza. Una modifica crea una nuova proposta da approvare.'},security:{name:'Laboratorio injection',label:'SICUREZZA / INPUT NON FIDATO',title:'Una mail non può riscrivere le regole.',text:'Prova un’istruzione injection. La demo la mette in quarantena e blocca l’uso non autorizzato degli strumenti.'},rejected:{name:'Rifiutata',label:'ESITO / CONSERVATA',title:'Rifiutata. Nulla è stato inviato.',text:'La bozza resta disponibile per l’ispezione. Il rifiuto non produce alcun invio.'},sent:{name:'Consegnata',label:'ESITO / CONSEGNATA',title:'Un invio ponderato.',text:'La risposta simulata è arrivata con l’autorizzazione registrata. Nessuna email reale è stata inviata.'}};
if(document.documentElement.lang==='it'){for(const [id,labels] of Object.entries(italianStations))Object.assign(stations[id],labels);}
const it=document.documentElement.lang==='it';
const L=it?{
 body:'Ciao Alex,\n\nGrazie della richiesta. La nostra proposta \u00e8 di 1.200 \u20ac per il progetto, con consegna entro due settimane.\n\nVuoi che ti mandiamo il perimetro completo?\n\nUn saluto,\nIl team',
 received:'Mail ricevuta da alex@example.com',
 needsHuman:'Serve l\u2019approvazione di una persona',
 ruleRequested:'Richiesta valutazione della regola di autopilot',
 revised:'Bozza revisionata; serve una nuova approvazione',
 ruleOk:'Autorizzata dalla regola sulle risposte di preventivo',
 ruleNo:'La regola non copre questa azione: serve revisione umana',
 approvedEdited:'Bozza revisionata approvata da te',
 approved:'Bozza approvata da te',
 rejected:'Rifiutata da te',
 quarantined:'Istruzione injection messa in quarantena; send_mail verso un destinatario esterno negata'
}:{
 body:'Hi Alex,\n\nThanks for your request. Our proposal is \u20ac1,200 for the project, with delivery within two weeks.\n\nWould you like us to send the full scope?\n\nBest,\nThe team',
 received:'Mail received from alex@example.com',
 needsHuman:'Human approval required',
 ruleRequested:'Autopilot rule evaluation requested',
 revised:'Draft revised; new approval required',
 ruleOk:'Authorized by the quote-reply rule',
 ruleNo:'Rule does not cover this action: human review required',
 approvedEdited:'Revised draft approved by you',
 approved:'Draft approved by you',
 rejected:'Rejected by you',
 quarantined:'Injected instruction quarantined; send_mail to outside recipient denied'
};
export class MailFlow {
 constructor(){this.reset();}
 reset(){this.stage='inbox';this.mode='semi';this.body=L.body;this.count=0;this.injection=false;this.ruleMatch=true;this.edited=false;this.reason='';this.log=[L.received];}
 next(){const paths={inbox:'llm',llm:'tools',tools:'draft',draft:'mode',semi:'approval'};if(paths[this.stage])this.stage=paths[this.stage];}
 lane(mode){if(this.stage!=='mode'||!['semi','auto'].includes(mode))return;this.mode=mode;this.stage=mode;this.log.push(mode==='semi'?L.needsHuman:L.ruleRequested);}
 edit(text){if(!['draft','approval'].includes(this.stage))return false;if(!text.trim())return false;this.body=text.trim();this.edited=true;this.log.push(L.revised);return true;}
 evaluate(){if(this.stage!=='auto')return;const allowed=this.ruleMatch&&!this.injection&&!this.edited&&this.count<3;this.stage=allowed?'sent':'approval';if(allowed){this.count++;this.reason=L.ruleOk;}else this.reason=L.ruleNo;this.log.push(this.reason);}
 decide(action){if(this.stage!=='approval'||!['approve','reject'].includes(action))return;if(action==='approve'){this.stage='sent';this.count++;this.reason=this.edited?L.approvedEdited:L.approved;}else{this.stage='rejected';this.reason=L.rejected;}this.log.push(this.reason);}
 attack(){this.returnStage=this.stage;this.stage='security';this.injection=true;this.log.push(L.quarantined);}
 resume(){if(this.stage!=='security')return;this.stage=this.returnStage||'llm';}
}
