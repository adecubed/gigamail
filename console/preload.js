const { contextBridge, shell, ipcRenderer } = require('electron');

const API = 'http://127.0.0.1:8002';

async function apiJson(url, options = {}) {
  const response = await fetch(url, options);
  const text = await response.text();

  let payload;
  try {
    payload = text ? JSON.parse(text) : {};
  } catch {
    payload = { raw: text };
  }

  if (!response.ok) {
    const message =
      payload?.detail ||
      payload?.message ||
      payload?.raw ||
      `HTTP ${response.status}`;
    throw new Error(String(message));
  }

  return payload;
}

async function apiBlob(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) {
    let text = '';
    try { text = await response.text(); } catch {}
    throw new Error(text || `HTTP ${response.status}`);
  }
  return response.blob();
}

contextBridge.exposeInMainWorld('electronAPI', {
  openExternal:   (url) => shell.openExternal(url),
  onOpenMail:     (callback) => ipcRenderer.on('open-mail', (_, data) => callback(data)),
  onNewMail:      (callback) => ipcRenderer.on('new-mail',  (_, data) => callback(data)),
  closeWindow:    () => ipcRenderer.send('window-close'),
  minimizeWindow: () => ipcRenderer.send('window-minimize'),
  maximizeWindow: () => ipcRenderer.send('window-maximize'),
  openMailWindow:   (data) => ipcRenderer.send('open-mail-window', data),
  onDockMailBack:      (cb)  => ipcRenderer.on('dock-mail-back', (_, data) => cb(data)),
  openMarketingWindow: ()    => ipcRenderer.send('open-marketing-window'),
  openAskWindow:       (data) => ipcRenderer.send('open-ask-window', data),
  openCalendarWindow:  ()    => ipcRenderer.send('open-calendar-window'),
  onOpenReplyFor:     (cb)  => ipcRenderer.on('open-reply-for', (_, data) => cb(data)),
  openNewMailWindow:  (data) => ipcRenderer.send('open-new-mail-window', data),
  openReplyWindow:    (data) => ipcRenderer.send('open-reply-window', data),
  toggleCompact: () => ipcRenderer.invoke('toggle-compact'),
  openAttachment:   (name, bytes) => ipcRenderer.invoke('mail-attachment-open',    { name, bytes }),
  saveAttachmentAs: (name, bytes) => ipcRenderer.invoke('mail-attachment-save-as', { name, bytes }),
});


contextBridge.exposeInMainWorld('ademail', {

  // ---------------------------------------------------------------- AUTH
  getStatus:      () => apiJson(`${API}/auth/status`),
  startLogin:     () => apiJson(`${API}/auth/login`),
  completeLogin:  () => apiJson(`${API}/auth/complete`, { method: 'POST' }),
  logout:         () => apiJson(`${API}/auth/logout`, { method: 'POST' }),

  // ---------------------------------------------------------------- ACCOUNTS
  getAccounts:      () => apiJson(`${API}/accounts`),
  getActiveAccount: () => apiJson(`${API}/accounts/active`),
  switchAccount:    (id) => apiJson(`${API}/accounts/active/${id}`, { method: 'POST' }),
  deleteAccount:    (id) => apiJson(`${API}/accounts/${id}`, { method: 'DELETE' }),
  getProviders:     () => apiJson(`${API}/accounts/providers`),

  addImapAccount: (name, email, password, provider, imapHost, imapPort, smtpHost, smtpPort) =>
    apiJson(`${API}/accounts/imap`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, email, password, provider,
        imap_host: imapHost, imap_port: imapPort,
        smtp_host: smtpHost, smtp_port: smtpPort }),
    }),

  // ---------------------------------------------------------------- MAIL
  getMail: (top = 20, skip = 0, priority = false, accountId = null) => {
    let url = `${API}/mail?top=${top}&skip=${skip}&priority=${priority}`;
    if (accountId) url += `&account_id=${accountId}`;
    return apiJson(url);
  },

  readMail: (id, accountId = null, folder = null) => {
    let url = `${API}/mail/${encodeURIComponent(id)}`;
    const params = [];
    if (accountId) params.push(`account_id=${encodeURIComponent(accountId)}`);
    if (folder) params.push(`folder=${encodeURIComponent(folder)}`);
    if (params.length) url += `?${params.join('&')}`;
    return apiJson(url);
  },

  getSummary: (id, accountId = null, folder = null) => {
    let url = `${API}/mail/${encodeURIComponent(id)}/summary`;
    const params = [];
    if (accountId) params.push(`account_id=${encodeURIComponent(accountId)}`);
    if (folder) params.push(`folder=${encodeURIComponent(folder)}`);
    if (params.length) url += `?${params.join('&')}`;
    return apiJson(url);
  },

  getFolderSuggestion: (id, accountId = null, folder = null) => {
    let url = `${API}/mail/${encodeURIComponent(id)}/folder_suggestion`;
    const params = [];
    if (accountId) params.push(`account_id=${encodeURIComponent(accountId)}`);
    if (folder) params.push(`folder=${encodeURIComponent(folder)}`);
    if (params.length) url += `?${params.join('&')}`;
    return apiJson(url);
  },

  replyDraft: (id, instruction, accountId = null, folder = null) => {
    let url = `${API}/mail/${encodeURIComponent(id)}/reply_draft`;
    const params = [];
    if (accountId) params.push(`account_id=${encodeURIComponent(accountId)}`);
    if (folder) params.push(`folder=${encodeURIComponent(folder)}`);
    if (params.length) url += `?${params.join('&')}`;
    return apiJson(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ instruction }),
    });
  },

  sendMail: (
    to,
    subject,
    body,
    replyToId = null,
    originalDraft = null,
    instruction = null,
    accountId = null,
    attachments = null,
    cc = null,
    bcc = null
  ) => {
    let url = `${API}/mail/send`;
    if (accountId) url += `?account_id=${accountId}`;
    return apiJson(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ to, subject, body,
        reply_to_id: replyToId, original_draft: originalDraft, instruction,
        attachments: attachments || [], cc: cc || [], bcc: bcc || [] }),
    });
  },

  searchMail: (q, accountId = null) => {
    let url = `${API}/mail/search/${encodeURIComponent(q)}`;
    if (accountId) url += `?account_id=${accountId}`;
    return apiJson(url);
  },

  getTtsUrl: (id, accountId = null, folder = null) => {
    let url = `${API}/mail/${encodeURIComponent(id)}/tts`;
    const params = [];
    if (accountId) params.push(`account_id=${encodeURIComponent(accountId)}`);
    if (folder) params.push(`folder=${encodeURIComponent(folder)}`);
    if (params.length) url += `?${params.join('&')}`;
    return url;
  },

  spamMail: (id, accountId = null, folder = null) => {
    let url = `${API}/mail/${encodeURIComponent(id)}/spam`;
    if (accountId) url += `?account_id=${accountId}`;
    if (folder) url += `${accountId ? '&' : '?'}folder=${encodeURIComponent(folder)}`;
    return apiJson(url, { method: 'POST' });
  },

  deleteMail: (id, accountId = null) => {
    let url = `${API}/mail/${encodeURIComponent(id)}`;
    if (accountId) url += `?account_id=${accountId}`;
    return apiJson(url, { method: 'DELETE' });
  },

  // ---------------------------------------------------------------- MAIL EXTRA
  getSentMail: (top = 20, accountId = null) => {
    let url = `${API}/mail/sent?top=${top}`;
    if (accountId) url += `&account_id=${accountId}`;
    return apiJson(url);
  },

  getDraftsMail: (top = 20, accountId = null) => {
    let url = `${API}/mail/drafts?top=${top}`;
    if (accountId) url += `&account_id=${accountId}`;
    return apiJson(url);
  },

  getSpamMail: (top = 20, accountId = null) => {
    let url = `${API}/mail/spam?top=${top}`;
    if (accountId) url += `&account_id=${accountId}`;
    return apiJson(url);
  },

  getDeletedMail: (top = 20, accountId = null) => {
    let url = `${API}/mail/deleted?top=${top}`;
    if (accountId) url += `&account_id=${accountId}`;
    return apiJson(url);
  },

  getFolderMail: (folderId, top = 20, accountId = null) => {
    let url = `${API}/mail/folder/${encodeURIComponent(folderId)}?top=${top}`;
    if (accountId) url += `&account_id=${accountId}`;
    return apiJson(url);
  },

  getMailFolders: (accountId = null) => {
    let url = `${API}/mail/folders`;
    if (accountId) url += `?account_id=${accountId}`;
    return apiJson(url);
  },

  createMailFolder: (name, keywords = [], accountId = null) => {
    let url = `${API}/mail/folders`;
    if (accountId) url += `?account_id=${accountId}`;
    return apiJson(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, keywords }),
    });
  },

  deleteMailFolder: (folderId, accountId = null) => {
    let url = `${API}/mail/folders/${encodeURIComponent(folderId)}`;
    if (accountId) url += `?account_id=${accountId}`;
    return apiJson(url, { method: 'DELETE' });
  },

  moveMailToFolder: (id, folderId, accountId = null, sourceFolder = null) => {
    let url = `${API}/mail/${encodeURIComponent(id)}/move`;
    const params = [];
    if (accountId) params.push(`account_id=${encodeURIComponent(accountId)}`);
    if (sourceFolder) params.push(`source_folder=${encodeURIComponent(sourceFolder)}`);
    if (params.length) url += `?${params.join('&')}`;
    return apiJson(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ folder_id: folderId }),
    });
  },

  saveDraft: (to, subject, body, accountId = null) =>
    apiJson(`${API}/mail/draft/save`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ to, subject, body, account_id: accountId }),
    }),

  getLocalDrafts: (accountId = null) => {
    let url = `${API}/mail/draft/local`;
    if (accountId) url += `?account_id=${accountId}`;
    return apiJson(url);
  },

  deleteLocalDraft: (id) => apiJson(`${API}/mail/draft/local/${id}`, { method: 'DELETE' }),

  getAddresses: (q = '', accountId = null) => {
    const params = new URLSearchParams({ q });
    if (accountId) params.append('account_id', accountId);
    return apiJson(`${API}/addresses/search?${params}`);
  },

  // ---------------------------------------------------------------- ALLEGATI
  getAttachmentUrl: (id, filename, accountId=null, folder = null) => {
    let url = `${API}/mail/${encodeURIComponent(id)}/attachment/${encodeURIComponent(filename)}`;
    const params = [];
    if (accountId) params.push(`account_id=${encodeURIComponent(accountId)}`);
    if (folder) params.push(`folder=${encodeURIComponent(folder)}`);
    if (params.length) url += `?${params.join('&')}`;
    return url;
  },

  // ---------------------------------------------------------------- OFFICE UPLOAD
  uploadFile: async (file) => {
    const formData = new FormData();
    formData.append('file', file);
    const res = await fetch(`${API}/office/upload`, { method: 'POST', body: formData });
    if (!res.ok) throw new Error(await res.text());
    return res.json();
  },

  // ---------------------------------------------------------------- OBSERVER
  getObserverStats: (accountId = null) => {
    let url = `${API}/observer/stats`;
    if (accountId) url += `?account_id=${accountId}`;
    return apiJson(url);
  },

  // ---------------------------------------------------------------- CALENDAR
  getEvents:         (days = 7) => apiJson(`${API}/calendar?days=${days}`),
  getTodaySummary:   () => apiJson(`${API}/calendar/today`),
  createEvent:       (data) => apiJson(`${API}/calendar`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) }),
  updateEvent:       (id, data) => apiJson(`${API}/calendar/${encodeURIComponent(id)}`, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) }),
  deleteEvent:       (id) => apiJson(`${API}/calendar/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  getCalendarTtsUrl: () => `${API}/calendar/today/tts`,

  // ---------------------------------------------------------------- OFFICE
  createExcel: (data, instruction, filename) =>
    apiJson(`${API}/office/excel`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ data, instruction, filename }) }),

  createWord: (instruction, sourceText, filename, title) =>
    apiJson(`${API}/office/word`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ instruction, source_text: sourceText, filename, title }) }),

  // ---------------------------------------------------------------- TTS
  speakText: (text) =>
    apiBlob(`${API}/tts`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
    }),

  // ---------------------------------------------------------------- IDENTITY
  getIdentity: (accountId) =>
    apiJson(`${API}/accounts/${accountId}/identity`),

  setIdentity: (accountId, data) =>
    apiJson(`${API}/accounts/${accountId}/identity`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }),

  readLocalFile: (path) =>
    apiJson(`${API}/files/local?path=${encodeURIComponent(path)}`),

  getFolderIdentity: (accountId, folderId) =>
    apiJson(`${API}/accounts/${accountId}/folder-identity/${encodeURIComponent(folderId)}`),

  setFolderIdentity: (accountId, folderId, data) =>
    apiJson(`${API}/accounts/${accountId}/folder-identity/${encodeURIComponent(folderId)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }),

  deleteFolderIdentity: (accountId, folderId) =>
    apiJson(`${API}/accounts/${accountId}/folder-identity/${encodeURIComponent(folderId)}`, {
      method: 'DELETE',
    }),

  // ---------------------------------------------------------------- BULK MAIL
  bulkUpload: async (file) => {
    const formData = new FormData();
    formData.append('file', file);
    const res = await fetch(`${API}/bulk/upload`, { method: 'POST', body: formData });
    if (!res.ok) throw new Error(await res.text());
    return res.json();
  },

  bulkStart: (payload, accountId = null) => {
    let url = `${API}/bulk/start`;
    if (accountId) url += `?account_id=${accountId}`;
    return apiJson(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
  },

  bulkStatus: () => apiJson(`${API}/bulk/status`),

  bulkStop: () => apiJson(`${API}/bulk/stop`, { method: 'POST' }),

  smartDraft: (id, accountId = null, folder = null) => {
    let url = `${API}/mail/${encodeURIComponent(id)}/smart_draft`;
    const params = [];
    if (accountId) params.push(`account_id=${encodeURIComponent(accountId)}`);
    if (folder) params.push(`folder=${encodeURIComponent(folder)}`);
    if (params.length) url += `?${params.join('&')}`;
    return apiJson(url, { method: 'POST' });
  },

  // ---------------------------------------------------------------- MAIL MEMORY
  mailMemoryStats: () => apiJson(`${API}/mail/memory/stats`),

  mailMemorySender: (email) =>
    apiJson(`${API}/mail/memory/sender/${encodeURIComponent(email)}`),

  mailMemoryIndex: (accountId = null) => {
    let url = `${API}/mail/memory/index`;
    if (accountId) url += `?account_id=${accountId}`;
    return apiJson(url, { method: 'POST' });
  },

  mailMemoryStop: () => apiJson(`${API}/mail/memory/stop`, { method: 'POST' }),

  mailMemoryIndexerState: (accountId = null) => {
    let url = `${API}/mail/memory/indexer_state`;
    if (accountId) url += `?account_id=${accountId}`;
    return apiJson(url);
  },

  bulkGenerate: (instruction, subjectHint = '') =>
    apiJson(`${API}/bulk/generate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ instruction, subject_hint: subjectHint }),
    }),

  // ---------------------------------------------------------------- VOICE
  transcribeAudio: async (audioBlob) => {
    const formData = new FormData();
    formData.append('audio', audioBlob, 'recording.webm');
    const res = await fetch(`${API}/voice/transcribe`, { method: 'POST', body: formData });
    if (!res.ok) throw new Error(await res.text());
    return res.json();
  },

  voiceCommand: (text, context = null, accountId = null) =>
    apiJson(`${API}/voice/command`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, context, account_id: accountId }),
    }),
});
