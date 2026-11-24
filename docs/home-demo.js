// The live demo on the home page: one email arrives, the agent reads it,
// the facts it finds in the user's files and calendar appear one by one,
// the draft waits for the OK, the reply is approved, and it starts again.
// It plays by itself (most visitors do not click a demo) and only while it
// is on screen. With reduced motion it shows the finished draft and stops.
// The words live in the page, so each language keeps its own; this script
// only moves the phases.

export const PHASES = ['mail', 'search', 'draft', 'sent'];

// How long each step lasts, in ms. `found` is per fact.
export const TIMING = { mail: 1600, found: 550, draft: 700, wait: 2600, sent: 2200 };

// The steps of one round, as [delay from the start in ms, phase, facts shown].
export function schedule(facts, timing = TIMING) {
  const steps = [[0, 'mail', 0]];
  let t = timing.mail;
  steps.push([t, 'search', 0]);
  for (let i = 1; i <= facts; i += 1) {
    t += timing.found;
    steps.push([t, 'search', i]);
  }
  t += timing.draft;
  steps.push([t, 'draft', facts]);
  t += timing.wait;
  steps.push([t, 'sent', facts]);
  t += timing.sent;
  return { steps, length: t };
}

// Shows one step: the phase on the root, `on` on the facts already found.
export function show(root, phase, shown) {
  root.setAttribute('data-phase', phase);
  root.querySelectorAll('.demo-facts li').forEach((li, i) => li.classList.toggle('on', i < shown));
}

export function startDemo(root, win) {
  if (!root) return null;
  win = win || window;
  const facts = root.querySelectorAll('.demo-facts li').length;
  const calm = !!(win.matchMedia && win.matchMedia('(prefers-reduced-motion: reduce)').matches);
  if (calm) {
    show(root, 'draft', facts);
    return { stop() {} };
  }
  const { steps, length } = schedule(facts);
  let timers = [];
  let playing = false;
  const clear = () => { timers.forEach((t) => win.clearTimeout(t)); timers = []; };
  const round = () => {
    clear();
    steps.forEach(([at, phase, shown]) => timers.push(win.setTimeout(() => show(root, phase, shown), at)));
    timers.push(win.setTimeout(round, length));
  };
  const play = () => { if (!playing) { playing = true; round(); } };
  const pause = () => { playing = false; clear(); };
  show(root, 'mail', 0);
  if ('IntersectionObserver' in win) {
    const io = new win.IntersectionObserver((entries) => {
      entries.forEach((e) => (e.isIntersecting ? play() : pause()));
    }, { threshold: 0.3 });
    io.observe(root);
    return { stop() { io.disconnect(); pause(); } };
  }
  play();
  return { stop: pause };
}

if (typeof window !== 'undefined' && typeof document !== 'undefined') {
  const go = () => startDemo(document.querySelector('.demo'));
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', go);
  else go();
}
