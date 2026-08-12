const { contextBridge, ipcRenderer } = require('electron');
contextBridge.exposeInMainWorld('newMailWindowAPI', {
  onLoadNewMail: (cb) => ipcRenderer.on('load-new-mail', (_, data) => cb(data)),
  close:         ()   => ipcRenderer.send('new-mail-window-close'),
  minimize:      ()   => ipcRenderer.send('new-mail-window-minimize'),
  maximize:      ()   => ipcRenderer.send('new-mail-window-maximize'),
  resizeTo:      (w, h) => ipcRenderer.send('window-resize', { w, h }),
  followupSave:  (data) => ipcRenderer.invoke('followup-save', data),
});
