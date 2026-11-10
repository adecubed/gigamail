// Unit tests of claude_login_panel.js: Automations says when Claude Code is
// not signed in and offers the sign-in there.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { JSDOM } = require('jsdom');

const CLAUDE = { agent: 'claude', available: true };

function load(api) {
  const dom = new JSDOM(`<!DOCTYPE html><body>
    <span id="agentStatus" class="ai-card-status ok">ready</span>
    <div id="claudeLoginBox" style="display:none"></div></body>`,
  { runScripts: 'outside-only' });
  const w = dom.window;
  w.electronAPI = api;
  vm.runInContext(fs.readFileSync(path.join(__dirname, '..', 'claude_login_panel.js'), 'utf-8'),
    dom.getInternalVMContext());
  w.ClaudeLoginPanel.POLL_MS = 1;
  return w;
}

const box = (w) => w.document.getElementById('claudeLoginBox');
const status = (w) => w.document.getElementById('agentStatus');
const loginButton = (w) => w.document.querySelector('[data-act="claude-login"]');

async function until(check) {
  for (let i = 0; i < 200; i += 1) {
    const v = check();
    if (v) return v;
    await new Promise((r) => setTimeout(r, 5));
  }
  throw new Error('condition never met');
}

test('signed out: the status stops saying ready and the button appears', async () => {
  const w = load({ claudeLoginStatus: async () => ({ pending: false, logged_in: false, url: '' }) });
  await w.ClaudeLoginPanel.refresh(CLAUDE);
  assert.ok(loginButton(w));
  assert.notEqual(box(w).style.display, 'none');
  assert.ok(status(w).className.includes('err'));
});

test('signed in: nothing is shown and the status is left alone', async () => {
  const w = load({ claudeLoginStatus: async () => ({ pending: false, logged_in: true, url: '' }) });
  await w.ClaudeLoginPanel.refresh(CLAUDE);
  assert.equal(loginButton(w), null);
  assert.equal(box(w).style.display, 'none');
  assert.equal(status(w).textContent, 'ready');
});

test('another agent, or none installed: the sign-in state is not even asked', async () => {
  let asked = 0;
  const w = load({ claudeLoginStatus: async () => { asked += 1; return {}; } });
  await w.ClaudeLoginPanel.refresh({ agent: 'codex', available: true });
  await w.ClaudeLoginPanel.refresh({ agent: 'claude', available: false });
  assert.equal(asked, 0);
  assert.equal(loginButton(w), null);
});

test('state unknown: nothing false is said', async () => {
  const w = load({ claudeLoginStatus: async () => { throw new Error('backend down'); } });
  await w.ClaudeLoginPanel.refresh(CLAUDE);
  assert.equal(loginButton(w), null);
  assert.equal(status(w).textContent, 'ready');
});

test('the button signs in and the panel closes when it is done', async () => {
  let started = 0;
  let polls = 0;
  const w = load({
    claudeLoginStart: async () => { started += 1; return { pending: true, logged_in: false, url: '' }; },
    claudeLoginStatus: async () => {
      polls += 1;
      return polls === 1 ? { pending: false, logged_in: false, url: '' }
        : { pending: false, logged_in: true, url: '' };
    },
  });
  await w.ClaudeLoginPanel.refresh(CLAUDE);
  loginButton(w).click();
  await until(() => box(w).style.display === 'none');
  assert.equal(started, 1);
  assert.ok(status(w).className.includes('ok'));
});

test('a refresh during the sign-in does not redraw it away', async () => {
  let done = false;
  let polling = false;
  const w = load({
    claudeLoginStart: async () => ({ pending: true, logged_in: false, url: '' }),
    claudeLoginStatus: async () => {
      if (polling) return { pending: !done, logged_in: done, url: '' };
      return { pending: false, logged_in: false, url: '' };
    },
  });
  await w.ClaudeLoginPanel.refresh(CLAUDE);
  polling = true;
  loginButton(w).click();
  await until(() => box(w).querySelector('.agent-login-wait'));
  await w.ClaudeLoginPanel.refresh(CLAUDE);
  assert.equal(loginButton(w), null);
  done = true;
  await until(() => box(w).style.display === 'none');
});

test('the manual page and the code reach the backend; a foreign address is not shown', async () => {
  const codes = [];
  let url = 'https://claude.ai/oauth/authorize?x=1';
  const w = load({
    claudeLoginStart: async () => ({ pending: true, logged_in: false, url }),
    claudeLoginStatus: async () => ({ pending: true, logged_in: false, url }),
    claudeLoginCode: async (c) => { codes.push(c); return {}; },
  });
  w.electronAPI.claudeLoginStatus = async () => ({ pending: false, logged_in: false, url: '' });
  await w.ClaudeLoginPanel.refresh(CLAUDE);
  w.electronAPI.claudeLoginStatus = async () => ({ pending: true, logged_in: false, url });
  loginButton(w).click();
  await until(() => w.document.querySelector('.agent-login-url'));
  assert.equal(w.document.querySelector('.agent-login-url').href, url);
  w.document.querySelector('.agent-login-code input').value = ' good-code ';
  w.document.querySelector('[data-act="claude-login-code"]').click();
  await until(() => codes.length);
  assert.equal(codes[0], 'good-code');

  url = 'https://evil.example.com/oauth/authorize?x';
  const other = load({
    claudeLoginStart: async () => ({ pending: true, logged_in: false, url }),
    claudeLoginStatus: async () => ({ pending: false, logged_in: false, url: '' }),
  });
  await other.ClaudeLoginPanel.refresh(CLAUDE);
  other.electronAPI.claudeLoginStatus = async () => ({ pending: true, logged_in: false, url });
  loginButton(other).click();
  await until(() => box(other).querySelector('.agent-login-wait'));
  await new Promise((r) => setTimeout(r, 30));
  assert.equal(other.document.querySelector('.agent-login-url'), null);

  // Both sign-ins are still pending and their panels keep asking, for as
  // long as a real sign-in may take: end them, or the test file never exits.
  for (const win of [w, other]) {
    win.electronAPI.claudeLoginStatus = async () => ({ pending: false, logged_in: false, url: '' });
    await until(() => loginButton(win));
  }
});
