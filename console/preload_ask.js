const { contextBridge, ipcRenderer } = require('electron');
// Base URL del backend, decisa dal main (ADE_CONSOLE_PORT) e passata qui
// via additionalArguments: la pagina la legge da window.GIGAMAIL_API.
const GIGAMAIL_API = ((process.argv || []).find((a) => a.startsWith('--gigamail-api=')) || '').slice('--gigamail-api='.length) || 'http://127.0.0.1:8002';
contextBridge.exposeInMainWorld('GIGAMAIL_API', GIGAMAIL_API);
contextBridge.exposeInMainWorld('askWindowAPI', {
  onLoad:    (cb) => ipcRenderer.on('load-ask', (_, data) => cb(data)),
  close:     ()   => ipcRenderer.send('ask-window-close'),
  minimize:  ()   => ipcRenderer.send('ask-window-minimize'),
  maximize:  ()   => ipcRenderer.send('ask-window-maximize'),
  openMail:  (data) => ipcRenderer.send('open-mail-window', data),
});
