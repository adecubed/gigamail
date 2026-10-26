"""Registra un video della scena, pilotando la console vera.

Niente cattura dello schermo: ogni finestra della console viene fotografata
dal suo renderer con Page.captureScreenshot e le immagini vengono composte
una sopra l'altra alle coordinate in cui le finestre stanno davvero. Cosi'
nel video entra solo l'applicazione, mai il resto del desktop di chi gira.

I click li fa il copione, con Runtime.evaluate sugli stessi elementi che
tocca un dito umano. Il puntatore che si vede e' disegnato sopra: serve a
far capire dove sta succedendo la cosa, e non esiste nel prodotto.

L'attesa della bozza (una ventina di secondi) viene compressa: durante
quel tratto i fotogrammi si prendono piu' radi, quindi nel montato scorre
veloce invece di essere tagliato di netto. Il tempo vero resta leggibile.

Prima di lanciare serve la console avviata con la porta di debug aperta:

    python demo_video/registra.py --avvia --scena 1

oppure, se la console e' gia' su quella porta:

    python demo_video/registra.py --scena 1
"""
import json
import math
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from base64 import b64decode
from io import BytesIO
from pathlib import Path

import allestimento as demo  # dirotta la radice dati, va importato per primo

from PIL import Image, ImageDraw, ImageFilter  # noqa: E402

PORTA = 9222
BASE = f"http://127.0.0.1:{PORTA}"
USCITA = demo.QUI / "video"
FRAME_DIR = demo.QUI / ".frame"
FPS = 30


# ── CDP ──────────────────────────────────────────────────────────────

def _targets():
    with urllib.request.urlopen(BASE + "/json", timeout=5) as r:
        return [t for t in json.load(r) if t.get("type") == "page"]


def trova(sottostringa, timeout=20):
    fine = time.time() + timeout
    while time.time() < fine:
        for t in _targets():
            testo = (t.get("url", "") + " " + t.get("title", "")).lower()
            if sottostringa.lower() in testo:
                return t
        time.sleep(0.3)
    raise RuntimeError(f"nessuna finestra con '{sottostringa}'")


def sparita(sottostringa, timeout=10):
    fine = time.time() + timeout
    while time.time() < fine:
        if not any(sottostringa.lower() in (t.get("url", "") + t.get("title", "")).lower()
                   for t in _targets()):
            return True
        time.sleep(0.3)
    return False


class Finestra:
    """Una finestra Electron: si pilota e si fotografa."""

    def __init__(self, target):
        import websocket  # websocket-client
        self.target = target
        # Senza suppress_origin Chromium rifiuta la connessione con 403.
        self.ws = websocket.create_connection(target["webSocketDebuggerUrl"],
                                              timeout=120, suppress_origin=True)
        self.n = 0

    def send(self, method, **params):
        self.n += 1
        self.ws.send(json.dumps({"id": self.n, "method": method, "params": params}))
        while True:
            m = json.loads(self.ws.recv())
            if m.get("id") == self.n:
                if "error" in m:
                    raise RuntimeError(m["error"])
                return m.get("result", {})

    def js(self, expr):
        r = self.send("Runtime.evaluate", expression=expr,
                      returnByValue=True, userGesture=True)
        if r.get("exceptionDetails"):
            raise RuntimeError(json.dumps(r["exceptionDetails"])[:400])
        return r.get("result", {}).get("value")

    def attendi(self, expr, timeout=180, passo=0.25):
        fine = time.time() + timeout
        while time.time() < fine:
            try:
                if self.js(expr):
                    return True
            except Exception:
                pass
            time.sleep(passo)
        return False

    def posizione(self):
        v = json.loads(self.js(
            "JSON.stringify({x:screenX,y:screenY,w:innerWidth,h:innerHeight})"))
        return v["x"], v["y"], v["w"], v["h"]

    def rect(self, selettore):
        """Centro di un elemento, in coordinate schermo."""
        v = self.js(
            "(() => { const e = document.querySelector(" + json.dumps(selettore) + ");"
            " if (!e) return ''; const r = e.getBoundingClientRect();"
            " return JSON.stringify({x:r.left+r.width/2+screenX,"
            " y:r.top+r.height/2+screenY}); })()")
        return json.loads(v) if v else None

    def sveglia(self):
        """Tiene la pagina in stato attivo anche quando la finestra sta
        dietro: una pagina 'frozen' si fotografa lentissima."""
        for stato in ("active",):
            try:
                self.send("Page.setWebLifecycleState", state=stato)
            except Exception:
                pass

    def scatta(self):
        r = self.send("Page.captureScreenshot", format="png",
                      captureBeyondViewport=False)
        return Image.open(BytesIO(b64decode(r["data"]))).convert("RGB")

    def chiudi(self):
        try:
            self.ws.close()
        except Exception:
            pass


# ── Il registratore ──────────────────────────────────────────────────

class Regia:
    """Compone i fotogrammi e tiene il conto del tempo del montato."""

    def __init__(self, principale: Finestra):
        self.principale = principale
        self.sopra = None            # finestra in primo piano, se c'e'
        self.frames = []             # (percorso, durata in secondi di video)
        self.n = 0
        self.velocita = 1.0          # >1 comprime il tempo reale
        self.cursore = None          # (x, y) schermo
        self.click = -99.0           # istante dell'ultimo click, per l'onda
        self.onda = 99.0
        self.tappe = []              # (secondo del montato, testo del sottotitolo)
        x, y, w, h = principale.posizione()
        self.origine = (x, y)
        self.tela = (w, h)
        FRAME_DIR.mkdir(parents=True, exist_ok=True)
        for vecchio in FRAME_DIR.glob("*.png"):
            vecchio.unlink()

    # -- composizione --

    def _sfondo(self) -> Image.Image:
        """Le finestre, composte. Costa due screenshot: si riusa quando in
        scena non si muove nulla tranne il puntatore."""
        tela = Image.new("RGBA", self.tela, (236, 240, 246, 255))
        tela.paste(self.principale.scatta(), (0, 0))
        if self.sopra is not None:
            try:
                sx, sy, _, _ = self.sopra.posizione()
                sopra = self.sopra.scatta()
                px = int(sx - self.origine[0])
                py = int(sy - self.origine[1])
                # Ombra morbida sotto la finestra in primo piano: un
                # rettangolo pieno la fa sembrare incollata sopra con lo
                # scotch, e in un fermo immagine si nota.
                ombra = Image.new("RGBA", tela.size, (0, 0, 0, 0))
                ImageDraw.Draw(ombra).rectangle(
                    [px - 6, py - 2, px + sopra.width + 6, py + sopra.height + 10],
                    fill=(20, 24, 32, 105))
                tela = Image.alpha_composite(
                    tela, ombra.filter(ImageFilter.GaussianBlur(14)))
                tela.paste(sopra, (px, py))
            except Exception:
                pass
        return tela

    def _puntatore(self, sfondo: Image.Image, onda: float = 99) -> Image.Image:
        tela = sfondo.copy()
        if not self.cursore:
            return tela.convert("RGB")
        x = int(self.cursore[0] - self.origine[0])
        y = int(self.cursore[1] - self.origine[1])
        d = ImageDraw.Draw(tela, "RGBA")
        if 0 <= onda < 0.45:
            raggio = int(10 + 34 * (onda / 0.45))
            alfa = int(150 * (1 - onda / 0.45))
            d.ellipse([x - raggio, y - raggio, x + raggio, y + raggio],
                      outline=(26, 108, 245, alfa), width=3)
        freccia = [(x, y), (x, y + 17), (x + 4, y + 13), (x + 7, y + 19),
                   (x + 10, y + 17), (x + 7, y + 11), (x + 12, y + 11)]
        d.polygon(freccia, fill=(255, 255, 255, 255),
                  outline=(20, 20, 20, 255))
        return tela.convert("RGB")

    # -- scrittura --

    def _scrivi(self, immagine: Image.Image, durata: float) -> None:
        self.n += 1
        percorso = FRAME_DIR / f"f{self.n:06d}.png"
        immagine.save(percorso)
        self.frames.append((percorso, durata))

    def scorre(self, secondi: float) -> None:
        """Fa passare del tempo registrando quello che succede davvero.

        La durata di ogni fotogramma e' il tempo che e' costato prenderlo,
        diviso la velocita' corrente: cosi' una pausa di cinque secondi
        dura cinque secondi anche nel montato, per quanto lenta sia la
        cattura. Con velocita' 8 gli stessi cinque secondi ne durano poco
        piu' di mezzo."""
        fine = time.time() + secondi
        while time.time() < fine:
            t0 = time.time()
            self.onda = t0 - self.click
            immagine = self._puntatore(self._sfondo(), self.onda)
            costo = max(time.time() - t0, 1.0 / FPS)
            self._scrivi(immagine, costo / self.velocita)

    def attende(self, finestra: Finestra, expr: str, timeout=180,
                velocita=8.0) -> bool:
        """Aspetta una condizione comprimendo il tempo: l'attesa della bozza
        nel montato dura pochi secondi invece di venti."""
        prima = self.velocita
        self.velocita = velocita
        try:
            fine = time.time() + timeout
            while time.time() < fine:
                try:
                    if finestra.js(expr):
                        return True
                except Exception:
                    pass
                self.scorre(0.35)
            return False
        finally:
            self.velocita = prima

    # -- gesti --

    def porta_il_cursore(self, punto, secondi=0.5) -> None:
        """Il puntatore si muove su uno sfondo fermo: si cattura una volta
        sola e si ridisegna solo la freccia. Trenta fotogrammi al secondo
        di movimento a costo di uno screenshot."""
        if punto is None:
            return
        meta = (punto["x"], punto["y"])
        if self.cursore is None:
            self.cursore = meta
            self.scorre(0.15)
            return
        sfondo = self._sfondo()
        passi = max(int(secondi * FPS), 2)
        x0, y0 = self.cursore
        for i in range(1, passi + 1):
            k = i / passi
            morbido = 0.5 - 0.5 * math.cos(math.pi * k)   # parte e finisce piano
            self.cursore = (x0 + (meta[0] - x0) * morbido,
                            y0 + (meta[1] - y0) * morbido)
            self._scrivi(self._puntatore(sfondo), 1.0 / FPS)
        self.cursore = meta

    def clicca(self, finestra: Finestra, selettore: str, pausa=0.7) -> None:
        punto = finestra.rect(selettore)
        if punto is None:
            raise RuntimeError(f"elemento non trovato: {selettore}")
        self.porta_il_cursore(punto)
        # L'onda del click viene disegnata a mano sullo sfondo fermo: il
        # gesto deve vedersi anche se la pagina non cambia subito.
        sfondo = self._sfondo()
        for i in range(int(0.28 * FPS)):
            self._scrivi(self._puntatore(sfondo, i / FPS), 1.0 / FPS)
        self.click = time.time()
        finestra.js("document.querySelector(" + json.dumps(selettore) + ").click()")
        self.scorre(pausa)

    # -- sottotitoli --

    def tempo(self) -> float:
        """Il secondo del montato a cui siamo adesso."""
        return sum(d for _, d in self.frames)

    def segna(self, testo: str) -> None:
        """Attacca un sottotitolo al punto in cui il copione e' arrivato.

        Scriverlo qui e non in un file a parte e' l'unico modo perche' resti
        agganciato a cio' che succede: la durata di ogni tratto cambia a
        ogni ripresa, perche' cambia quanto ci mette l'agente."""
        self.tappe.append((self.tempo(), testo))

    # -- consegna --

    def monta(self, nome: str) -> Path:
        USCITA.mkdir(parents=True, exist_ok=True)
        elenco = FRAME_DIR / "elenco.txt"
        with open(elenco, "w", encoding="utf-8") as f:
            for percorso, durata in self.frames:
                f.write(f"file '{percorso.as_posix()}'\n")
                f.write(f"duration {durata:.5f}\n")
            if self.frames:
                f.write(f"file '{self.frames[-1][0].as_posix()}'\n")
        fuori = USCITA / nome
        ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
        cmd = [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(elenco),
               "-vf", f"fps={FPS},format=yuv420p", "-c:v", "libx264",
               "-preset", "medium", "-crf", "20", str(fuori)]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError("ffmpeg: " + r.stderr[-800:])
        # Le tappe accanto al video: e' quello che legge il montatore per
        # scrivere i sottotitoli senza indovinare i tempi.
        with open(fuori.with_suffix(".json"), "w", encoding="utf-8") as f:
            json.dump({"durata": round(self.tempo(), 3),
                       "tappe": [{"t": round(t, 3), "testo": s}
                                 for t, s in self.tappe]},
                      f, ensure_ascii=False, indent=2)
        return fuori


# ── Il copione della scena 1 ─────────────────────────────────────────

def apri_mail(regia: Regia, principale: Finestra, cartella: str, id_mail: str,
              leggi=1.6) -> None:
    regia.clicca(principale,
                 f'.custom-folder-chip[data-folder-id="{cartella}"]', pausa=1.4)
    regia.clicca(principale, f'.mail-item[data-id="{id_mail}"]', pausa=leggi)


def apri_risposta(regia: Regia, principale: Finestra) -> Finestra:
    # Il bottone Rispondi vive dentro il dettaglio, che viene ricostruito a
    # ogni apertura: prima si aspetta che ci sia.
    principale.attendi("!!document.getElementById('btnShowReply')", timeout=20)
    regia.clicca(principale, "#btnShowReply", pausa=0.6)
    risposta = Finestra(trova("reply_window"))
    risposta.sveglia()
    risposta.attendi("!!document.getElementById('btnGenerate')", timeout=20)
    regia.sopra = risposta
    return risposta


def chiudi_risposta(regia: Regia, risposta: Finestra, pausa=0.9) -> None:
    try:
        regia.clicca(risposta, "#btnClose", pausa=0.3)
    finally:
        regia.sopra = None
        risposta.chiudi()
    sparita("reply_window", timeout=8)
    regia.scorre(pausa)


def genera(regia: Regia, risposta: Finestra, attesa_min=80) -> None:
    """Preme GENERA e aspetta la bozza, comprimendo l'attesa."""
    regia.clicca(risposta, "#btnGenerate", pausa=0.4)
    regia.attende(
        risposta,
        "(document.getElementById('replyText').value||'').length > "
        + str(attesa_min) + " || document.getElementById('guardBanner')"
        ".style.display === 'block'",
        timeout=180, velocita=8.0)


def leggi_bozza(regia: Regia, risposta: Finestra, secondi=5.5,
                allegati=2.4) -> None:
    """Il puntatore si sposta via dal bottone: la bozza si legge meglio
    senza una freccia piantata in mezzo."""
    regia.porta_il_cursore(risposta.rect("#replySubject") or
                           risposta.rect("#replyText"), secondi=0.6)
    regia.scorre(secondi)
    if allegati and risposta.js(
            "document.getElementById('suggestedBanner').style.display !== 'none'"):
        regia.porta_il_cursore(risposta.rect("#suggestedBanner"))
        regia.scorre(allegati)


# I sottotitoli spiegano, non descrivono: chi guarda vede gia' i click.
# Stanno qui accanto al copione perche' il momento in cui compaiono e' il
# punto del copione, non un secondo deciso a tavolino.
TAPPE = {
    (1, "apre_lead"): {
        "it": "Una richiesta arriva nella cartella Lead.",
        "en": "A request lands in the Leads folder.",
    },
    (1, "bozza_lead"): {
        "it": "La risposta e' breve e propone i due orari che quella cartella ha.",
        "en": "The reply is short and offers the two slots that folder holds.",
    },
    (1, "apre_clienti"): {
        "it": "La stessa identica domanda, ma archiviata fra i Clienti.",
        "en": "The very same question, but filed under Clients.",
    },
    (1, "bozza_clienti"): {
        "it": "Formale, cita i dati, e dove non ha l'informazione lascia un marcatore.",
        "en": "Formal, quotes the data, and leaves a marker where it has nothing.",
    },
    (1, "chiusura"): {
        "it": "Fra le due risposte non e' stata toccata nessuna impostazione.",
        "en": "Nothing was changed between the two replies.",
    },
    (3, "domanda"): {
        "it": "Un contatto nuovo chiede il prezzo e se il box e' compreso.",
        "en": "A new contact asks the price and whether the garage is included.",
    },
    (3, "bozza"): {
        "it": "La cifra viene dal listino dell'utente, letto sul momento.",
        "en": "The figure comes from the seller's own price list, read on the spot.",
    },
    (3, "allegati"): {
        "it": "E la scheda dell'appartamento viene proposta in allegato.",
        "en": "And the unit's data sheet is proposed as an attachment.",
    },
    (4, "domanda"): {
        "it": "Adesso la domanda e' sulle convenzioni bancarie per il mutuo.",
        "en": "Now the question is about bank arrangements for the mortgage.",
    },
    (4, "bozza"): {
        "it": "Il prezzo e' confermato. Sulla banca, nei documenti non c'e' nulla.",
        "en": "The price is confirmed. On the bank, the documents say nothing.",
    },
    (4, "marcatore"): {
        "it": "Dove non sa, lascia un buco visibile invece di inventare.",
        "en": "Where it does not know, it leaves a visible gap instead of inventing.",
    },
    (7, "attacco"): {
        "it": "Dentro questa mail ci sono istruzioni rivolte all'assistente.",
        "en": "This mail carries instructions addressed to the assistant.",
    },
    (7, "fermata"): {
        "it": "Nessuna bozza. Il controllo gira prima, e nessun modello legge la mail.",
        "en": "No draft. The check runs first, and no model reads the mail.",
    },
    (7, "destinatario"): {
        "it": "Il destinatario resta chi ha scritto, non l'indirizzo richiesto.",
        "en": "The recipient is still the sender, not the address that was asked for.",
    },
}


def sot(regia: Regia, scena: int, chiave: str, lingua: str) -> None:
    regia.segna(TAPPE[(scena, chiave)][lingua])


def scena_1(regia: Regia, principale: Finestra, lingua: str) -> None:
    """La stessa domanda in due cartelle: la risposta cambia."""
    regia.scorre(1.2)
    for quale, id_mail, apre, bozza in (
            ("lead", "1001", "apre_lead", "bozza_lead"),
            ("clienti", "1004", "apre_clienti", "bozza_clienti")):
        sot(regia, 1, apre, lingua)
        apri_mail(regia, principale, demo.cartella(lingua, quale), id_mail)
        risposta = apri_risposta(regia, principale)
        regia.scorre(1.4)
        genera(regia, risposta)
        sot(regia, 1, bozza, lingua)
        leggi_bozza(regia, risposta)
        chiudi_risposta(regia, risposta)
    sot(regia, 1, "chiusura", lingua)
    regia.scorre(2.4)


def scena_3(regia: Regia, principale: Finestra, lingua: str) -> None:
    """Il prezzo viene dal listino, e la scheda finisce in allegato."""
    regia.scorre(1.2)
    sot(regia, 3, "domanda", lingua)
    apri_mail(regia, principale, demo.cartella(lingua, "lead"), "1001", leggi=3.2)
    risposta = apri_risposta(regia, principale)
    regia.scorre(1.2)
    genera(regia, risposta)
    sot(regia, 3, "bozza", lingua)
    regia.porta_il_cursore(risposta.rect("#replySubject"), secondi=0.6)
    regia.scorre(6.0)
    sot(regia, 3, "allegati", lingua)
    regia.porta_il_cursore(risposta.rect("#suggestedBanner"))
    regia.scorre(4.0)
    chiudi_risposta(regia, risposta, pausa=1.2)


def scena_4(regia: Regia, principale: Finestra, lingua: str) -> None:
    """Il dato vero e il limite dichiarato, nella stessa frase."""
    regia.scorre(1.2)
    sot(regia, 4, "domanda", lingua)
    apri_mail(regia, principale, demo.cartella(lingua, "lead"), "1002", leggi=4.0)
    risposta = apri_risposta(regia, principale)
    regia.scorre(1.2)
    genera(regia, risposta)
    sot(regia, 4, "bozza", lingua)
    regia.porta_il_cursore(risposta.rect("#replySubject"), secondi=0.6)
    regia.scorre(4.5)
    sot(regia, 4, "marcatore", lingua)
    regia.scorre(4.5)
    chiudi_risposta(regia, risposta, pausa=1.2)


def scena_7(regia: Regia, principale: Finestra, lingua: str) -> None:
    """La mail che da' ordini all'assistente non produce nessuna bozza."""
    regia.scorre(1.2)
    sot(regia, 7, "attacco", lingua)
    apri_mail(regia, principale, demo.cartella(lingua, "lead"), "1003", leggi=5.0)
    risposta = apri_risposta(regia, principale)
    regia.scorre(1.2)
    genera(regia, risposta)
    # Niente bozza: si guarda l'avviso, e poi il campo del destinatario, che
    # e' rimasto il mittente originale e non l'indirizzo che la mail chiedeva.
    sot(regia, 7, "fermata", lingua)
    regia.porta_il_cursore(risposta.rect("#guardBanner"), secondi=0.7)
    regia.scorre(6.5)
    sot(regia, 7, "destinatario", lingua)
    regia.porta_il_cursore(risposta.rect("#replyTo"), secondi=0.8)
    regia.scorre(4.0)
    chiudi_risposta(regia, risposta, pausa=1.2)


COPIONI = {
    1: ("scena1_due_cartelle", scena_1),
    3: ("scena3_dato_dai_documenti", scena_3),
    4: ("scena4_limite_dichiarato", scena_4),
    7: ("scena7_mail_ostile", scena_7),
}


# ── Avvio ────────────────────────────────────────────────────────────

def avvia_console() -> None:
    """Apre la console sulla radice della demo con la porta di debug."""
    # L'eseguibile vero, non il .cmd di npm: il wrapper passa da cmd.exe e
    # gli argomenti con i trattini a volte non arrivano dall'altra parte.
    electron = (demo.RADICE / "console" / "node_modules" / "electron" /
                "dist" / "electron.exe")
    env = dict(os.environ)
    env["GIGAMAIL_ROOT"] = str(demo.STATO)
    env["ADE_ROOT"] = str(demo.STATO)
    # Senza queste tre, appena la finestra finisce dietro a qualcos'altro
    # Chromium la strozza: captureScreenshot passa da un quarto di secondo a
    # qualche secondo, e il montato esce a scatti perche' ogni fotogramma si
    # porta dietro il tempo che e' costato prenderlo.
    subprocess.Popen([str(electron), ".", f"--remote-debugging-port={PORTA}",
                      "--disable-background-timer-throttling",
                      "--disable-renderer-backgrounding",
                      "--disable-backgrounding-occluded-windows"],
                     cwd=str(demo.RADICE / "console"), env=env,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    fine = time.time() + 60
    while time.time() < fine:
        try:
            urllib.request.urlopen(BASE + "/json/version", timeout=2)
            return
        except Exception:
            time.sleep(0.5)
    raise RuntimeError("la console non ha aperto la porta di debug")


def prepara_interfaccia(principale: Finestra, lingua: str) -> Finestra:
    """Interfaccia nella lingua della scena, e casella aperta sulla posta in
    arrivo, come all'avvio. Una console inglese con dentro mail italiane non
    si puo' riprendere, quindi la lingua si sposta tutta insieme.

    Dopo il reload la connessione va rifatta: il contesto di esecuzione
    della pagina non e' piu' quello a cui eravamo attaccati, e la prima
    chiamata dopo cade con la connessione persa."""
    principale.js("try{localStorage.setItem('ade_lang','"
                  + lingua + "')}catch(e){}")
    try:
        principale.send("Page.reload")
    except Exception:
        pass
    principale.chiudi()
    time.sleep(3.0)
    fresca = Finestra(trova("index_v2", timeout=40))
    fresca.sveglia()
    fresca.attendi("!!document.querySelector('.custom-folder-chip')", timeout=40)
    fresca.js("document.querySelector('.custom-folder-home')?.click()")
    time.sleep(1.2)
    return fresca


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    argomenti = sys.argv[1:]
    scena = 1
    lingua = "it"
    if "--scena" in argomenti:
        i = argomenti.index("--scena")
        if i + 1 < len(argomenti):
            scena = int(argomenti[i + 1])
    if "--lingua" in argomenti:
        i = argomenti.index("--lingua")
        if i + 1 < len(argomenti):
            lingua = argomenti[i + 1]
    if scena not in COPIONI:
        print(f"Scene registrabili: {', '.join(str(s) for s in COPIONI)}")
        return 2

    demo.prepara(scena, lingua=lingua)
    print(f"Casella allestita per la scena {scena}, lingua {lingua}.")

    if "--avvia" in argomenti:
        avvia_console()

    # La console appena aperta si assesta: carica, applica la lingua e
    # ricarica. Chi si attacca troppo presto si ritrova la connessione
    # caduta sotto le mani, quindi si riprova invece di morire.
    principale = None
    for tentativo in range(3):
        try:
            principale = prepara_interfaccia(
                Finestra(trova("index_v2", timeout=40)), lingua)
            break
        except Exception as e:
            print(f"  la console non era pronta ({type(e).__name__}), riprovo")
            time.sleep(3)
    if principale is None:
        print("La console non risponde. Chiudila e rilancia con --avvia.")
        return 2

    radice, copione = COPIONI[scena]
    nome = f"{radice}_{lingua}.mp4"
    regia = Regia(principale)
    print(f"Registro {regia.tela[0]}x{regia.tela[1]}...")
    inizio = time.time()
    try:
        copione(regia, principale, lingua)
    finally:
        principale.chiudi()
    reali = time.time() - inizio
    ritmo = regia.n / max(reali, 1)
    print(f"{regia.n} fotogrammi in {reali:.0f} secondi reali "
          f"({ritmo:.1f} al secondo).")
    if ritmo < 2.0:
        print("  Attenzione: cattura lenta, il montato uscira' a scatti. "
              "Di solito e' la finestra strozzata perche' sta dietro: "
              "rilancia con --avvia.")

    fuori = regia.monta(nome)
    durata = sum(d for _, d in regia.frames)
    print(f"Video: {fuori}  ({durata:.1f} secondi)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
