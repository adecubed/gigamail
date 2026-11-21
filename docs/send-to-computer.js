// On a phone or tablet, GigaMail cannot be installed: each row of download
// buttons becomes one "Send to my computer" button. It opens the phone's
// share sheet (AirDrop, WhatsApp, an email to yourself, Notes...) with the
// link to gigamail.ai; where there is no share sheet it copies the link.
// Nothing is collected: the visitor sends the link wherever they like.
// One 'send_link' event is counted when the link was actually shared or
// copied, so we can see whether phone visitors use it.
import {analyticsConfig} from './business/analytics-config.js';
import {deviceInfo, track} from './business/analytics.js';

export const SHARE_URL = 'https://gigamail.ai/?utm_source=send-to-computer';

const TEXT = {
  en: {button: 'Send to my computer', title: 'GigaMail',
       message: 'GigaMail, to install on my computer',
       copied: 'Link copied. Open it on your computer.',
       hint: 'GigaMail is a desktop app for Windows, macOS and Linux.',
       updates: 'Or get an email when a new version is out'},
  it: {button: 'Mandalo al mio computer', title: 'GigaMail',
       message: 'GigaMail, da installare sul mio computer',
       copied: 'Link copiato. Aprilo dal computer.',
       hint: 'GigaMail è un’app desktop per Windows, macOS e Linux.',
       updates: 'Oppure ricevi un’email quando esce una nuova versione'},
  zh: {button: '发送到我的电脑', title: 'GigaMail',
       message: 'GigaMail，在我的电脑上安装',
       copied: '链接已复制。请在电脑上打开。',
       hint: 'GigaMail 是适用于 Windows、macOS 和 Linux 的桌面应用。',
       updates: '或者在新版本发布时收到邮件'},
};

export function textFor(lang) {
  return TEXT[(lang || 'en').slice(0, 2).toLowerCase()] || TEXT.en;
}

export function isHandheld(nav) {
  const {device} = deviceInfo(nav);
  return device === 'mobile' || device === 'tablet';
}

// 'shared', 'copied', or '' when the visitor closed the share sheet or
// nothing worked.
export async function sendLink(nav, t) {
  if (nav.share) {
    try {
      await nav.share({title: t.title, text: t.message, url: SHARE_URL});
      return 'shared';
    } catch (e) {
      if (e && e.name === 'AbortError') return '';
    }
  }
  try {
    await nav.clipboard.writeText(SHARE_URL);
    return 'copied';
  } catch { return ''; }
}

export function install(doc = document, win = window, config = analyticsConfig) {
  if (!isHandheld(win.navigator)) return 0;
  const t = textFor(doc.documentElement.lang);
  const rows = [...doc.querySelectorAll('.dl3')];
  const updates = doc.getElementById('updates');
  rows.forEach(row => {
    const box = doc.createElement('div');
    box.className = 'send-computer';
    const button = doc.createElement('button');
    button.type = 'button';
    button.className = 'btn btn-primary';
    button.textContent = t.button;
    const note = doc.createElement('p');
    note.className = 'send-note';
    note.textContent = t.hint;
    button.addEventListener('click', async () => {
      const how = await sendLink(win.navigator, t);
      if (!how) return;
      if (how === 'copied') note.textContent = t.copied;
      track('send_link', {text: how}, config, win);
    });
    box.append(button, note);
    if (updates) {
      const link = doc.createElement('a');
      link.className = 'send-updates';
      link.href = '#updates';
      link.textContent = t.updates;
      box.append(link);
    }
    row.hidden = true;
    row.after(box);
  });
  return rows.length;
}

if (typeof window !== 'undefined') install();
