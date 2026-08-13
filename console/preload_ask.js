const { contextBridge, ipcRenderer } = require('electron');
contextBridge.exposeInMainWorld('askWindowAPI', {
  onLoad:    (cb) => ipcRenderer.on('load-ask', (_, data) => cb(data)),
  close:     ()   => ipcRenderer.send('ask-window-close'),
  minimize:  ()   => ipcRenderer.send('ask-window-minimize'),
  maximize:  ()   => ipcRenderer.send('ask-window-maximize'),
  openMail:  (data) => ipcRenderer.send('open-mail-window', data),
});
