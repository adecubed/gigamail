// render.mjs — turn a seekable animation page into an mp4 and a poster.
//
//   node demo_video/animations/render.mjs agent_chat [--lang it] [--poster 13.2]
//
// The page exposes window.seek(seconds) and window.DURATION. A headless
// Chrome draws each frame on request and ffmpeg encodes them, so nothing
// depends on the speed of the machine. Needs Chrome or Edge, ffmpeg on the
// PATH, and the `ws` package the console already installs.
import { spawn } from 'node:child_process';
import { createRequire } from 'node:module';
import { existsSync, mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const repo = path.resolve(here, '..', '..');
const WebSocket = createRequire(path.join(repo, 'console', 'package.json'))('ws');

const args = process.argv.slice(2);
const name = args[0];
const option = (flag, fallback) => { const i = args.indexOf(flag); return i >= 0 ? args[i + 1] : fallback; };
const lang = option('--lang', 'en');
const posterAt = Number(option('--poster', '13.2'));
const FPS = 30, WIDTH = 1280, HEIGHT = 720;
if (!name) { console.error('usage: node render.mjs <animation> [--lang en|it] [--poster seconds]'); process.exit(2); }

const suffix = lang === 'en' ? '' : '-' + lang;
const slug = name.replace(/_/g, '-');
const outDir = path.join(repo, 'docs', 'demo');
const video = path.join(outDir, `gigamail-${slug}${suffix}.mp4`);
const poster = path.join(outDir, `gigamail-${slug}${suffix}-poster.jpg`);

const browsers = [
  process.env.CHROME_PATH,
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  '/usr/bin/google-chrome', '/usr/bin/chromium',
].filter(Boolean);
const browser = browsers.find((candidate) => existsSync(candidate));
if (!browser) { console.error('No Chrome or Edge found; set CHROME_PATH.'); process.exit(1); }

const profile = mkdtempSync(path.join(tmpdir(), 'gigamail-render-'));
const port = 9300 + Math.floor(Math.random() * 500);
const chrome = spawn(browser, [
  '--headless=new', `--remote-debugging-port=${port}`, `--user-data-dir=${profile}`,
  `--window-size=${WIDTH},${HEIGHT}`, '--hide-scrollbars', '--force-device-scale-factor=1',
  '--allow-file-access-from-files', '--no-first-run', 'about:blank',
], { stdio: 'ignore' });

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
async function target() {
  for (let i = 0; i < 80; i++) {
    try {
      const list = await (await fetch(`http://127.0.0.1:${port}/json`)).json();
      const page = list.find((entry) => entry.type === 'page');
      if (page) return page.webSocketDebuggerUrl;
    } catch { /* not up yet */ }
    await sleep(150);
  }
  throw new Error('the browser did not start');
}

let failed = false;
try {
  const socket = new WebSocket(await target());
  await new Promise((resolve, reject) => { socket.once('open', resolve); socket.once('error', reject); });
  let id = 0;
  const waiting = new Map();
  socket.on('message', (raw) => {
    const message = JSON.parse(raw);
    if (message.id && waiting.has(message.id)) { waiting.get(message.id)(message); waiting.delete(message.id); }
  });
  const send = (method, params = {}) => new Promise((resolve, reject) => {
    const mine = ++id;
    waiting.set(mine, (message) => (message.error ? reject(new Error(method + ': ' + message.error.message)) : resolve(message.result)));
    socket.send(JSON.stringify({ id: mine, method, params }));
  });
  const evaluate = async (expression) => {
    const result = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
    if (result.exceptionDetails) throw new Error(result.exceptionDetails.text + ' in ' + expression);
    return result.result.value;
  };

  await send('Emulation.setDeviceMetricsOverride', { width: WIDTH, height: HEIGHT, deviceScaleFactor: 1, mobile: false });
  await send('Page.enable');
  await send('Page.navigate', { url: pathToFileURL(path.join(here, name + '.html')).href + `?still&lang=${lang}` });
  for (let i = 0; i < 100 && !(await evaluate('typeof window.seek === "function"').catch(() => false)); i++) await sleep(100);
  await evaluate('document.fonts.ready.then(() => true)');
  const duration = await evaluate('window.DURATION');
  const shot = async (seconds, format, quality) => {
    await evaluate(`window.seek(${seconds}); new Promise(r => requestAnimationFrame(() => requestAnimationFrame(() => r(true))))`);
    const { data } = await send('Page.captureScreenshot', { format, quality, clip: { x: 0, y: 0, width: WIDTH, height: HEIGHT, scale: 1 } });
    return Buffer.from(data, 'base64');
  };

  const ffmpeg = spawn('ffmpeg', ['-y', '-loglevel', 'error', '-f', 'image2pipe', '-framerate', String(FPS), '-c:v', 'png', '-i', '-',
    '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-preset', 'slow', '-crf', '23', '-movflags', '+faststart', '-an', video],
  { stdio: ['pipe', 'inherit', 'inherit'] });
  const encoded = new Promise((resolve, reject) => ffmpeg.on('close', (code) => (code === 0 ? resolve() : reject(new Error('ffmpeg exited with ' + code)))));
  const frames = Math.round(duration * FPS);
  for (let frame = 0; frame < frames; frame++) {
    const png = await shot(frame / FPS, 'png');
    if (!ffmpeg.stdin.write(png)) await new Promise((resolve) => ffmpeg.stdin.once('drain', resolve));
    if (frame % 90 === 0) console.log(`frame ${frame} / ${frames}`);
  }
  ffmpeg.stdin.end();
  await encoded;

  const jpg = await shot(posterAt, 'jpeg', 88);
  const { writeFileSync } = await import('node:fs');
  writeFileSync(poster, jpg);
  console.log('wrote', path.relative(repo, video), 'and', path.relative(repo, poster));
  socket.close();
} catch (error) {
  failed = true;
  console.error(error.message);
} finally {
  chrome.kill();
  await sleep(400);
  try { rmSync(profile, { recursive: true, force: true }); } catch { /* the browser may still hold the folder */ }
}
process.exit(failed ? 1 : 0);
