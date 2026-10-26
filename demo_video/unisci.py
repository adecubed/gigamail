"""Cuce le quattro scene in un video solo, con cartelli e sottotitoli.

I quattro file separati restano dove sono: questo ne produce un quinto.

I tempi dei sottotitoli non sono decisi qui. Ogni scena, quando viene
registrata, lascia accanto al suo mp4 un file .json con i punti del
copione: quanto dura un tratto cambia a ogni ripresa, perche' cambia
quanto ci mette l'agente a scrivere, e sottotitoli scritti a tavolino
scivolerebbero via al primo rifacimento.

Uso:
    python demo_video/unisci.py --lingua en
    python demo_video/unisci.py --lingua it --scene 1,3,4,7
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import allestimento as demo  # dirotta la radice dati, va importato per primo

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

USCITA = demo.QUI / "video"
LAVORO = demo.QUI / ".montaggio"
FPS = 30
CARTELLO = 2.6   # secondi di cartello davanti a ogni scena
FASCIA = 76      # altezza della fascia sotto, dove vivono i sottotitoli

NOMI = {1: "scena1_due_cartelle", 3: "scena3_dato_dai_documenti",
        4: "scena4_limite_dichiarato", 7: "scena7_mail_ostile"}

TITOLO_FILE = {"it": "gigamail_demo_it.mp4", "en": "gigamail_demo_en.mp4"}

APERTURA = {
    "it": ("GigaMail", "La posta, letta dal tuo agente"),
    "en": ("GigaMail", "Your mailbox, read by your agent"),
}

CODA = {
    "it": ("Quattro scene, nessun trucco",
           "Console vera, casella su file, nessuna mail spedita"),
    "en": ("Four scenes, no tricks",
           "Real console, mailbox on a file, no mail ever sent"),
}


def _font(dimensione: int, grassetto=False):
    for nome in (("segoeuib.ttf", "seguisb.ttf") if grassetto
                 else ("segoeui.ttf",)):
        try:
            return ImageFont.truetype(f"C:/Windows/Fonts/{nome}", dimensione)
        except Exception:
            continue
    return ImageFont.load_default()


def cartello(path: Path, misura, occhiello: str, titolo: str,
             sottotitolo: str = "") -> Path:
    """Un fermo di stacco fra una scena e l'altra. Sfondo scuro e poche
    parole: serve a far respirare, non a spiegare."""
    largo, alto = misura
    img = Image.new("RGB", misura, (17, 20, 27))
    d = ImageDraw.Draw(img)
    f_occhiello = _font(20, True)
    f_titolo = _font(52, True)
    f_sotto = _font(24)

    y = alto // 2 - (80 if sottotitolo else 60)
    if occhiello:
        d.text((largo // 2, y), occhiello.upper(), font=f_occhiello,
               fill=(120, 160, 255), anchor="mm")
        y += 54
    d.text((largo // 2, y), titolo, font=f_titolo, fill=(240, 243, 250),
           anchor="mm")
    y += 62
    if sottotitolo:
        d.text((largo // 2, y), sottotitolo, font=f_sotto, fill=(150, 160, 180),
               anchor="mm")
    img.save(path)
    return path


def _ffmpeg(*args) -> None:
    exe = shutil.which("ffmpeg") or "ffmpeg"
    r = subprocess.run([exe, "-y", "-loglevel", "error", *args],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("ffmpeg: " + r.stderr[-900:])


def clip_da_immagine(png: Path, mp4: Path, secondi: float) -> Path:
    _ffmpeg("-loop", "1", "-t", f"{secondi}", "-i", str(png),
            "-vf", f"fps={FPS},format=yuv420p", "-c:v", "libx264",
            "-preset", "medium", "-crf", "20", str(mp4))
    return mp4


def _tempo(secondi: float) -> str:
    ms = int(round(secondi * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def scrivi_srt(path: Path, righe) -> Path:
    """righe: (inizio, fine, testo) in secondi. Questo e' il file che va
    consegnato a chi rimonta, non quello che si brucia nel video."""
    with open(path, "w", encoding="utf-8") as f:
        for i, (a, b, testo) in enumerate(righe, 1):
            f.write(f"{i}\n{_tempo(a)} --> {_tempo(b)}\n{testo}\n\n")
    return path


def _tempo_ass(secondi: float) -> str:
    cs = int(round(secondi * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"


def scrivi_ass(path: Path, righe, largo: int, alto: int) -> Path:
    """Il file che si brucia nel video.

    Non si usa l'SRT: ffmpeg lo converte assumendo una risoluzione sua,
    e poi libass scala tutto sull'altezza vera. Il risultato e' un corpo
    tre volte piu' grande di quello chiesto, sbrodolato sopra la console.
    Scrivendo l'ASS con PlayRes uguale al video, il corpo e' quello che si
    scrive e basta."""
    testa = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {largo}\nPlayResY: {alto}\n"
        "WrapStyle: 0\nScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        "Style: Base,Arial,27,&H00F2F4FA,&H00F2F4FA,&H0011141B,&H0011141B,"
        "0,0,0,0,100,100,0,0,1,0,0,2,70,70,20,1\n\n"
        "[Events]\n"
        # MarginV va elencato: senza, i valori scritti sotto scalano di uno
        # e la virgola dell'Effect finisce stampata davanti al testo.
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
        "Effect, Text\n"
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write(testa)
        for a, b, testo in righe:
            pulito = testo.replace("\n", " ").replace("{", "(").replace("}", ")")
            f.write(f"Dialogue: 0,{_tempo_ass(a)},{_tempo_ass(b)},Base,,"
                    f"0,0,0,,{pulito}\n")
    return path


def durata(mp4: Path) -> float:
    exe = shutil.which("ffprobe") or "ffprobe"
    r = subprocess.run([exe, "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", str(mp4)],
                       capture_output=True, text=True)
    return float(r.stdout.strip())


def misura(mp4: Path):
    exe = shutil.which("ffprobe") or "ffprobe"
    r = subprocess.run([exe, "-v", "error", "-select_streams", "v:0",
                        "-show_entries", "stream=width,height", "-of", "csv=p=0",
                        str(mp4)], capture_output=True, text=True)
    w, h = r.stdout.strip().split(",")[:2]
    return int(w), int(h)


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    argomenti = sys.argv[1:]
    lingua = "en"
    scene = [1, 3, 4, 7]
    if "--lingua" in argomenti:
        i = argomenti.index("--lingua")
        if i + 1 < len(argomenti):
            lingua = argomenti[i + 1]
    if "--scene" in argomenti:
        i = argomenti.index("--scene")
        if i + 1 < len(argomenti):
            scene = [int(x) for x in argomenti[i + 1].split(",")]

    pezzi = []
    for s in scene:
        mp4 = USCITA / f"{NOMI[s]}_{lingua}.mp4"
        if not mp4.exists():
            print(f"Manca {mp4.name}. Registrala con:")
            print(f"  python demo_video/registra.py --scena {s} --lingua {lingua}")
            return 2
        manifesto = mp4.with_suffix(".json")
        if not manifesto.exists():
            print(f"Manca {manifesto.name}: la scena {s} e' stata registrata "
                  "prima dei sottotitoli. Rigirala.")
            return 2
        pezzi.append((s, mp4, json.loads(manifesto.read_text(encoding="utf-8"))))

    LAVORO.mkdir(parents=True, exist_ok=True)
    for vecchio in LAVORO.glob("*"):
        vecchio.unlink()
    dim = misura(pezzi[0][1])

    # Cartelli, video e sottotitoli, tutti sulla stessa linea del tempo.
    pista, righe, t = [], [], 0.0
    occhiello, titolo = APERTURA[lingua]
    apri = clip_da_immagine(
        cartello(LAVORO / "apertura.png", dim, "", occhiello, titolo),
        LAVORO / "apertura.mp4", 3.0)
    pista.append(apri)
    t += 3.0

    for s, mp4, manifesto in pezzi:
        etichetta = "SCENA" if lingua == "it" else "SCENE"
        card = clip_da_immagine(
            cartello(LAVORO / f"c{s}.png", dim, f"{etichetta} {s}",
                     demo.SCENE[s]["titolo"][lingua]),
            LAVORO / f"c{s}.mp4", CARTELLO)
        pista.append(card)
        t += CARTELLO

        tappe = manifesto.get("tappe", [])
        lunga = durata(mp4)
        for i, tappa in enumerate(tappe):
            inizio = t + float(tappa["t"])
            fine = (t + float(tappe[i + 1]["t"])) if i + 1 < len(tappe) else (t + lunga)
            # Un sottotitolo che resta appeso mezzo minuto stanca: dopo sei
            # secondi sparisce, anche se il tratto continua.
            fine = min(fine, inizio + 6.0)
            if fine > inizio + 0.6:
                righe.append((inizio, fine, tappa["testo"]))
        pista.append(mp4)
        t += lunga

    occhiello, sotto = CODA[lingua]
    chiudi = clip_da_immagine(
        cartello(LAVORO / "coda.png", dim, "", occhiello, sotto),
        LAVORO / "coda.mp4", 3.4)
    pista.append(chiudi)
    t += 3.4

    elenco = LAVORO / "pista.txt"
    with open(elenco, "w", encoding="utf-8") as f:
        for p in pista:
            f.write(f"file '{Path(p).as_posix()}'\n")
    srt = scrivi_srt(LAVORO / "sottotitoli.srt", righe)
    ass = scrivi_ass(LAVORO / "sottotitoli.ass", righe, dim[0], dim[1] + FASCIA)

    fuori = USCITA / TITOLO_FILE[lingua]
    # I sottotitoli vanno in una fascia aggiunta sotto, non sopra la
    # console: appoggiati sull'immagine coprivano proprio le cose che la
    # scena vuole mostrare, cioe' gli allegati proposti e i bottoni.
    # Il filtro subtitles vuole un percorso senza due punti, quindi si usa
    # il nome relativo dopo essersi messi nella cartella di lavoro.
    exe = shutil.which("ffmpeg") or "ffmpeg"
    cmd = [exe, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
           "-i", str(elenco),
           "-vf", (f"pad=iw:ih+{FASCIA}:0:0:color=0x11141B,"
                   f"subtitles={ass.name}"),
           "-c:v", "libx264", "-preset", "medium", "-crf", "20",
           "-pix_fmt", "yuv420p", str(fuori)]
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=str(LAVORO))
    if r.returncode != 0:
        raise RuntimeError("ffmpeg: " + r.stderr[-900:])

    # Anche l'srt accanto al video: chi rimonta lo vuole separato.
    shutil.copyfile(srt, fuori.with_suffix(".srt"))
    print(f"Video unico: {fuori}  ({durata(fuori):.1f} secondi)")
    print(f"Sottotitoli: {fuori.with_suffix('.srt')}  ({len(righe)} righe)")
    print("I quattro video separati sono rimasti dove erano.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
