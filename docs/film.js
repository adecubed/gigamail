// GigaMail — il sito come un film guidato dallo scroll.
// Ogni capitolo e' una sequenza di fotogrammi (film/<shot>/f_0001.webp ...) renderizzata in Blender;
// la pagina ha una sezione alta per capitolo, e la posizione di scroll dentro la sezione sceglie il fotogramma.
// Un solo <canvas> fisso disegna il fotogramma corrente; le didascalie HTML stanno sopra.
//
// Uso:  mountFilm({ canvas, chapters: [{ el, shot: "01", frames: 72, small: true }, ...] })
// I bottoni possono chiamare film.play(chapterIndex, from, to) per un'animazione autonoma (es. l'approvazione).

const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
const narrow = () => innerWidth < 700 || (innerWidth < 1000 && innerWidth < innerHeight);

function frameUrl(shot, i, small) {
  return `film/${shot}/${small ? "m/" : ""}f_${String(i).padStart(4, "0")}.webp`;
}

// carica i fotogrammi di una sequenza, prima quelli radi (ogni 6) per avere subito qualcosa, poi tutti
function loadSequence(shot, frames, small, onProgress) {
  const imgs = new Array(frames + 1).fill(null);
  let loaded = 0;
  const load = (i) => new Promise((res) => {
    const im = new Image();
    im.onload = () => { imgs[i] = im; loaded++; onProgress && onProgress(loaded / frames); res(im); };
    im.onerror = () => res(null);
    im.src = frameUrl(shot, i, small);
  });
  const coarse = []; for (let i = 1; i <= frames; i += 6) coarse.push(i);
  const fine = []; for (let i = 1; i <= frames; i++) if ((i - 1) % 6) fine.push(i);
  const ready = Promise.all(coarse.map(load)).then(() => { fine.forEach(load); });
  return { imgs, ready, nearest(i) {   // il fotogramma piu' vicino gia' caricato
    i = Math.max(1, Math.min(frames, Math.round(i)));
    if (imgs[i]) return imgs[i];
    for (let d = 1; d < frames; d++) { if (imgs[i - d]) return imgs[i - d]; if (imgs[i + d]) return imgs[i + d]; }
    return null;
  } };
}

export function mountFilm({ canvas, chapters, onChapter }) {
  const ctx = canvas.getContext("2d", { alpha: false });
  const small = narrow();
  const seqs = chapters.map((c) => loadSequence(c.shot, c.frames, small && c.small !== false));
  let dpr = Math.min(devicePixelRatio || 1, 2), W = 0, H = 0;
  function resize() {
    W = innerWidth; H = innerHeight; dpr = Math.min(devicePixelRatio || 1, 2);
    canvas.width = Math.round(W * dpr); canvas.height = Math.round(H * dpr);
    canvas.style.width = W + "px"; canvas.style.height = H + "px";
    draw(true);
  }
  addEventListener("resize", resize);

  // stato: capitolo corrente e "testa" del fotogramma (puo' essere spinta da play() oltre lo scroll)
  const state = { ch: -1, frame: 1, playing: null, last: null };

  function progressOf(i) {   // 0..1 dentro la sezione i
    const r = chapters[i].el.getBoundingClientRect();
    const span = r.height - H;
    return span <= 0 ? 0 : Math.max(0, Math.min(1, -r.top / span));
  }
  function current() {
    let best = 0, bestD = Infinity;
    chapters.forEach((c, i) => { const r = c.el.getBoundingClientRect(); const d = Math.abs(r.top + Math.min(r.height, H) / 2 - H / 2); if (d < bestD) { bestD = d; best = i; } });
    return best;
  }

  function drawImage(im) {
    // cover: riempie tutto lo schermo mantenendo le proporzioni
    const s = Math.max(canvas.width / im.naturalWidth, canvas.height / im.naturalHeight);
    const w = im.naturalWidth * s, h = im.naturalHeight * s;
    ctx.drawImage(im, (canvas.width - w) / 2, (canvas.height - h) / 2, w, h);
  }

  function draw(force) {
    const ch = current();
    if (ch !== state.ch) { state.ch = ch; state.playing = null; onChapter && onChapter(ch); }
    const c = chapters[ch];
    let f;
    if (state.playing) {
      const p = state.playing; const k = Math.min(1, (performance.now() - p.t0) / p.ms);
      f = p.from + (p.to - p.from) * (k < 0.5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2);
      if (k >= 1) { state.playing = null; p.done && p.done(); }
    } else {
      f = 1 + progressOf(ch) * (c.frames - 1);
    }
    const im = seqs[ch].nearest(f);
    if (im && (force || im !== state.last)) { drawImage(im); state.last = im; }
  }

  let raf = 0;
  const tick = () => { draw(false); raf = requestAnimationFrame(tick); };
  resize();
  seqs[0].ready.then(() => { draw(true); tick(); });

  return {
    // animazione autonoma dentro il capitolo corrente, dal fotogramma from al fotogramma to
    play(ch, from, to, ms = 1400, done) { if (ch !== state.ch) return; state.playing = { from, to, t0: performance.now(), ms, done }; },
    goTo(i) { chapters[i].el.scrollIntoView({ behavior: reduced ? "auto" : "smooth", block: "start" }); },
    current: () => state.ch,
    progress: () => progressOf(state.ch),
    seqs,
  };
}
