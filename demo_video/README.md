# Demo — quattro video, dati finiti, casella finta

Quattro video corti, uno per scena, non un video solo. Ogni scena si
allestisce da sola: in casella entra solo cio' che le serve, cosi'
l'inquadratura e' pulita e il ciak si rifa' identico quante volte serve.

| Video | Scena | Dura |
|---|---|---|
| 1 | La stessa domanda, due cartelle | 40-50 secondi |
| 2 | Il dato esce dai documenti | 30-40 secondi |
| 3 | Il limite dichiarato | 30-40 secondi |
| 4 | La mail che da' ordini all'assistente | 40-50 secondi |

I numeri di scena restano quelli di sempre: 1, 3, 4 e 7. Il video 2 gira la
scena 3, il video 3 gira la scena 4, il video 4 gira la scena 7.

Si gira sulla console vera, con una casella che sta su un file invece che
su un server di posta. Nessuna connessione, nessuna credenziale, nessun
messaggio che esce davvero: cio' che l'agente invia finisce nella posta
inviata del file. Non e' una modalita' globale e non si accende con una
variabile d'ambiente: la casella finta esiste solo perche' esiste un
account di tipo `demo`, e l'installer non ne crea nessuno.

Dati, account e identity vivono in `demo_video/dati` e `demo_video/.stato`,
tutti e due fuori dal repository. La posta e la configurazione vere non
vengono mai toccate.

## Girare da soli, senza telecamera

```bash
python demo_video/registra.py --avvia --scena 1 --lingua it
```

Allestisce la scena, apre la console con la porta di debug, la pilota e
consegna un mp4 in `demo_video/video`. Se la console e' gia' aperta su
quella porta, si lascia via `--avvia`. Le lingue sono `it` e `en`.

La lingua sposta tutto insieme: interfaccia, documenti, identity e mail.
Una console inglese con dentro un listino italiano non si puo' riprendere.
Le bozze non hanno bisogno di impostazioni, perche' seguono la lingua della
mail ricevuta.

Non e' una cattura dello schermo: ogni finestra viene fotografata dal suo
renderer e le immagini vengono composte alle coordinate in cui le finestre
stanno davvero, quindi nel video entra solo l'applicazione e mai il resto
del desktop. I click li fa il copione sugli stessi elementi che tocca un
dito umano; il puntatore che si vede e' disegnato sopra e nel prodotto non
esiste. L'attesa della bozza scorre a velocita' otto, cosi' il montato
resta sui tre quarti di minuto senza tagli secchi.

## Come si gira a mano

```bash
python demo_video/allestisci.py --scena 1
```

Allestisce la casella per quella scena e stampa il foglio di ripresa: cosa
si vede, cosa si fa, cosa deve succedere, la voce e cosa non dire. Le scene
sono 1, 3, 4 e 7. Senza `--scena` entrano tutte le mail insieme. I fogli
sono scritti in italiano; per girare in inglese si usa il registratore.

Poi si lancia la console sulla radice della demo:

```bash
$env:GIGAMAIL_ROOT = "C:\Users\simon\Desktop\ade_mail_agent\demo_video\.stato"; npm --prefix console start
```

Fra un ciak e l'altro, per rimettere la scena al via:

```bash
python demo_video/allestisci.py --riparti --scena 1
```

`--stato` mostra cosa c'e' in casella adesso, senza toccare niente.

Una bozza esce in una ventina di secondi. Durante l'attesa il bottone
GENERA diventa un puntino: in montaggio quel pezzo va tagliato.

## Cucire le scene in un video solo

```bash
python demo_video/unisci.py --lingua en
```

Mette in fila le quattro scene con un cartello di stacco davanti a
ciascuna, e brucia i sottotitoli in una fascia aggiunta sotto, dove non
coprono la console. I quattro file separati restano dove sono: questo ne
produce un quinto, piu' un `.srt` accanto per chi rimonta.

I tempi dei sottotitoli non sono scritti a mano. Ogni scena, mentre viene
registrata, lascia accanto al suo mp4 un `.json` con i punti del copione:
quanto dura un tratto cambia a ogni ripresa, perche' cambia quanto ci mette
l'agente a scrivere, e sottotitoli decisi a tavolino scivolerebbero via al
primo rifacimento. Il testo dei sottotitoli sta in `registra.py`, accanto
al gesto che spiega.

## La prova a vuoto

Le stesse scene, verificate senza telecamera e senza interfaccia, sugli
stessi dati:

```bash
python demo_video/preflight_test.py --lingua en
```

`--mostra` stampa le bozze e gli allegati proposti, `--scena 4` gira una
scena sola. L'uscita e' 0 se passano tutte le verifiche, 1 altrimenti, 2 se
non c'e' un agente configurato. Se una verifica fallisce qui, fallisce
anche davanti alla telecamera.

## I dati

Una cartella di conoscenza con quattro file: il listino dei quattro
appartamenti, le condizioni di vendita, e le schede di A12 e B08 in PDF.
Il prezzo dell'A12 e' 395.000 euro con box auto incluso, e sta sia nel
listino sia nella scheda. Di convenzioni bancarie non si parla in nessun
file: e' quello che rende girabile la scena 4.

L'account ha una identity generale e due identity di cartella, Lead e
Clienti, con tono e istruzioni diversi. Gli slot per le visite stanno in
chiaro dentro `key_info` della cartella Lead: senza calendario collegato il
modello se li inventerebbe, e un orario finto in un video sull'affidabilita'
e' esattamente cio' che non serve.

La fattura di settembre resta in casella in tutte le scene: una casella con
dentro una mail sola non assomiglia a una casella, e in ripresa si vede.

## I quattro fogli

Sono stampati da `allestisci.py --scena N`, cosi' chi gira ce li ha davanti
senza aprire questo file. Qui restano per leggerli tutti insieme.

### Video 1 — La stessa domanda, due cartelle (scena 1)

In casella ci sono due cartelle. In Lead c'e' Giulia Rossi, in Clienti c'e'
Marco Bianchi, e le due mail chiedono la stessa identica cosa.

Si apre la mail di Giulia in Lead, si preme GENERA, si legge la bozza:
breve, e propone i due orari per la visita. Poi si apre la mail di Marco in
Clienti e si preme GENERA. La seconda risposta e' formale, riepiloga i dati
e scrive `[DA COMPLETARE]` sulla visita, perche' quella cartella gli orari
non li ha. Fra le due riprese non si tocca nessuna impostazione.

Voce: la cartella in cui sta la mail decide chi risponde. Non e' un modello
diverso, e' la stessa richiesta letta con l'identita' della cartella.

### Video 2 — Il dato esce dai documenti (scena 3)

In Lead una sola mail: Giulia chiede prezzo e box. Si preme GENERA, si
inquadra la cifra nella bozza e poi il riquadro ALLEGATI SUGGERITI con
`scheda_A12.pdf`. Se serve la prova, si apre il listino nella cartella dei
documenti e si mostra la stessa riga.

Voce: il prezzo non se lo inventa il modello, viene dal listino
dell'utente, letto sul momento e messo davanti a chi scrive.

### Video 3 — Il limite dichiarato (scena 4)

In Lead la seconda mail di Giulia, che chiede conferma del prezzo e se ci
sono convenzioni bancarie per il mutuo. Si legge la domanda ad alta voce, si
preme GENERA, fermo immagine sulla frase con il prezzo e sul marcatore.

Voce: il dato vero e il limite nella stessa frase. Dove non sa, lascia un
buco visibile invece di riempirlo.

### Video 4 — La mail che da' ordini all'assistente (scena 7)

In Lead una mail dello studio legale, con dentro istruzioni rivolte
all'assistente. Si legge ad alta voce il passaggio, si preme GENERA. Non
compare nessuna bozza: al suo posto una fascia rossa dice cosa e' stato
riconosciuto e cita il passaggio. Il campo del testo resta vuoto, nessun
allegato viene proposto, il modello non e' stato nemmeno chiamato. Si chiude
inquadrando il campo A, dove c'e' il mittente originale e non l'indirizzo
che la mail chiedeva.

Voce: il controllo gira prima della generazione e non interpella nessun
modello, quindi il testo che analizza non puo' convincerlo.

## Cosa NON dire in voce

- **L'agente non controlla il calendario.** Nella demo gli slot vengono
  dall'identity di cartella, scritti a mano. Con un calendario collegato
  `find_free_slots` li calcola davvero, ma qui non e' collegato, e la
  finestra del calendario e' vuota: non va inquadrata.
- **Il presidio riconosce schemi, non capisce.** Copre le formulazioni
  note; chi scrive in modo diverso puo' passare. E' il primo strato. La
  difesa che regge resta strutturale: il destinatario di una risposta non
  si sposta, e le azioni pericolose passano da un'approvazione umana.
- **Il presidio copre solo `smart_draft`.** E' l'unico percorso in cui il
  testo di una mail ricevuta entra nel prompt. Gli altri percorsi che
  generano testo partono da cio' che scrive l'utente e non sono agganciati.
- **L'agente non sa cosa non sa.** Sa cosa c'e' nei documenti, e per il
  resto ha l'ordine di lasciare il marcatore.
