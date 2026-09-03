const { contextBridge, ipcRenderer } = require('electron');
// Base URL del backend, decisa dal main (ADE_CONSOLE_PORT) e passata qui
// via additionalArguments: la pagina la legge da window.GIGAMAIL_API.
const GIGAMAIL_API = ((process.argv || []).find((a) => a.startsWith('--gigamail-api=')) || '').slice('--gigamail-api='.length) || 'http://127.0.0.1:8002';
contextBridge.exposeInMainWorld('GIGAMAIL_API', GIGAMAIL_API);
contextBridge.exposeInMainWorld('replyWindowAPI', {
  onLoadReply: (cb) => ipcRenderer.on('load-reply', (_, data) => cb(data)),
  ready:       ()   => ipcRenderer.send('reply-window-ready'),
  close:       ()   => ipcRenderer.send('reply-window-close'),
  minimize:    ()   => ipcRenderer.send('reply-window-minimize'),
  maximize:    ()   => ipcRenderer.send('reply-window-maximize'),
  resizeTo:    (w, h) => ipcRenderer.send('window-resize', { w, h }),
  followupSave: (data) => ipcRenderer.invoke('followup-save', data),
});
