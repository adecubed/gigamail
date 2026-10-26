# GigaMail /real-estate

Nuova landing statica italiana. Tutti i file preesistenti sono invariati.

## Integrazione nel repository pubblico

Copia la cartella `dist/real-estate` di questo progetto in `docs/real-estate` del repository adecubed/gigamail (la web root della landing). Non sostituire docs/index.html, docs/it.html o i CSS della home.

La pagina usa il bundle Three.js già esistente in `/vendor/three/build/three.module.js` e `/vendor/three/build/three.core.js`. CSS e script della nuova pagina sono isolati sotto `/real-estate/`.

Il server deve risolvere `/real-estate` verso `/real-estate/index.html` (la normale risoluzione directory index, eventualmente con redirect finale `/`, è sufficiente). I riferimenti assoluti funzionano in entrambi i casi.

## Richieste demo — configurazione necessaria

In `real-estate/config.js`, imposta UNA destinazione verificata:

```js
export const demoConfig = { endpoint: '/api/demo', email: '' };
```

Il valore `/api/demo` è un esempio da sostituire con un endpoint reale. Contratto: POST JSON `{name, agency, email, phone}`; risposta 2xx JSON `{"ok":true}` solo dopo ricezione confermata. Il backend deve validare input, limitare abusi e gestire la consegna. Nessun endpoint viene creato da questa landing statica.

In alternativa, imposta `email` all'indirizzo che deve ricevere le richieste, lasciando endpoint vuoto. Il browser aprirà una mail precompilata; il visitatore completa l'invio nel proprio client. Il sito non dichiara che la mail sia già inviata.

Finché entrambi sono vuoti il form informa esplicitamente che non è configurato e non invia dati. Non è pronto a raccogliere contatti finché questa configurazione manca.

## Interazione

- Scena WebGL con etichette HTML accessibili e nodi cliccabili; Escape chiude il dettaglio.
- Scroll nativo senza cattura della rotella: rete → messaggi sparsi → convergenza → quattro categorie.
- Mobile: meno particelle, DPR limitato, touch senza parallax.
- Reduced motion: rete statica; nessun loop continuo né scorrimento narrativo prolungato.
- WebGL indisponibile o import fallito: diagramma statico e nodi utilizzabili.
- Animazione sospesa fuori viewport, tab nascosta o pulsante pausa.
- Le simulazioni non interrogano email e non eseguono autenticazione biometrica o invii.

## Verifiche eseguite

Sintassi JS, selettori DOM, unicità ID, collegamenti interni, asset, label form, confronto byte per byte di tutti i file preesistenti. Nessuna verifica browser eseguita in questa sessione. La versione è salvata, non pubblicata.
