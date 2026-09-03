const { contextBridge, ipcRenderer } = require('electron');
// Base URL del backend, decisa dal main (ADE_CONSOLE_PORT) e passata qui
// via additionalArguments: la pagina la legge da window.GIGAMAIL_API.
const GIGAMAIL_API = ((process.argv || []).find((a) => a.startsWith('--gigamail-api=')) || '').slice('--gigamail-api='.length) || 'http://127.0.0.1:8002';
contextBridge.exposeInMainWorld('GIGAMAIL_API', GIGAMAIL_API);
contextBridge.exposeInMainWorld('newMailWindowAPI', {
  onLoadNewMail: (cb) => ipcRenderer.on('load-new-mail', (_, data) => cb(data)),
  close:         ()   => ipcRenderer.send('new-mail-window-close'),
  minimize:      ()   => ipcRenderer.send('new-mail-window-minimize'),
  maximize:      ()   => ipcRenderer.send('new-mail-window-maximize'),
  resizeTo:      (w, h) => ipcRenderer.send('window-resize', { w, h }),
  followupSave:  (data) => ipcRenderer.invoke('followup-save', data),
});
